from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from bot.config import Settings
from bot.services.access_service import AccessService
from bot.services.financial_service import FinancialService
from bot.services.panel_service import PanelService


def _owner_id_from_comment(comment: str) -> int | None:
    owner_raw = comment.strip().split(":", 1)[0].strip()
    return int(owner_raw) if owner_raw.isdigit() else None


def _delegate_finance_comment_tag(comment: str) -> str | None:
    raw = comment.strip()
    if ":" not in raw:
        return None
    tail = raw.split(":", 1)[1].strip()
    if tail.lower() == "moafresume":
        return "moafresume"
    if tail.lower() == "moaf":
        return "moaf"
    return None


def _delegate_finance_client_out_of_scope(
    *,
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    comment: str,
    owner_id_set: set[str],
    exclude_remaining_keys: set[tuple[int, int, str]],
    moaf_exempt_for_scope: set[tuple[int, str]],
) -> bool:
    if (panel_id, inbound_id, client_uuid) in exclude_remaining_keys:
        return True
    if (inbound_id, client_uuid) in moaf_exempt_for_scope:
        return True
    fin_tag = _delegate_finance_comment_tag(comment)
    comment_owner_id = _owner_id_from_comment(comment)
    if fin_tag == "moaf" and comment_owner_id is not None and str(comment_owner_id) in owner_id_set:
        return True
    return False


def _billable_segment_totals(
    *,
    segments: list[dict[str, Any]],
    owner_id_set: set[str],
    current_total_bytes: int,
    used_bytes: int,
) -> tuple[int, int, int, int]:
    owner_ids = {str(segment.get("owner_user_id") or "") for segment in segments if segment.get("is_billable")}
    if not owner_ids.intersection(owner_id_set):
        return 0, 0, 0, 0
    allocated = 0
    consumed = 0
    allocated_consumed = 0
    for segment in segments:
        if not segment.get("is_billable"):
            continue
        if str(segment.get("owner_user_id") or "") not in owner_id_set:
            continue
        start = max(0, int(segment.get("start_bytes") or 0))
        end = max(start, int(segment.get("end_bytes") or 0))
        capped_end = min(end, current_total_bytes)
        if capped_end <= start:
            continue
        segment_consumed = max(0, min(used_bytes, capped_end) - start)
        consumed += segment_consumed
        if bool(segment.get("_consumed_only")):
            continue
        allocated += capped_end - start
        allocated_consumed += segment_consumed
    return 1, allocated, consumed, max(allocated - allocated_consumed, 0)


def _valid_report_segments(
    *,
    segments: list[dict[str, Any]],
    comment: str,
    root_admin_id_set: set[str],
) -> list[dict[str, Any]]:
    if not segments:
        return []
    comment_owner_id = _owner_id_from_comment(comment)
    valid_segments: list[dict[str, Any]] = []
    for segment in segments:
        if str(segment.get("source") or "") != "parent_detach_snapshot":
            valid_segments.append(segment)
            continue
        if comment_owner_id is None or str(comment_owner_id) in root_admin_id_set:
            consumed_only = dict(segment)
            consumed_only["_consumed_only"] = True
            valid_segments.append(consumed_only)
            continue
        valid_segments.append(segment)
    return valid_segments


@dataclass
class ScopeFinancialLedger:
    delegate_finance_excluded_used_bytes: int = 0
    clients_count: int = 0
    allocated_bytes: int = 0
    consumed_bytes: int = 0
    remaining_bytes: int = 0
    panel_total_consumed_bytes: int = 0
    root_created_consumed_bytes: int = 0
    billable_segment_consumed_bytes: int = 0


class ProvisioningFinancialSummaryService:
    def __init__(
        self,
        *,
        db: Any,
        panel_service: PanelService,
        access_service: AccessService,
        financial_service: FinancialService | None = None,
    ) -> None:
        self.db = db
        self.panel_service = panel_service
        self.access_service = access_service
        self.financial_service = financial_service

    async def financial_scope_user_ids(self, *, actor_user_id: int, settings: Settings) -> list[int]:
        context = await self.access_service.get_admin_context(actor_user_id, settings)
        if context.is_root_admin:
            return []
        if context.is_delegated_admin:
            fn = getattr(self.db, "get_delegated_admin_financial_scope_user_ids", None)
            if fn is not None:
                return await fn(manager_user_id=actor_user_id, include_self=True)
            return await self.db.get_delegated_admin_subtree_user_ids(manager_user_id=actor_user_id, include_self=True)
        return [actor_user_id]

    async def _merged_delegate_finance_exclusions_for_actor(
        self, *, actor_user_id: int
    ) -> tuple[set[tuple[int, int]], set[tuple[int, int, str]]]:
        excluded_inbounds: set[tuple[int, int]] = set()
        exclude_remaining_keys: set[tuple[int, int, str]] = set()
        inbound_loader = getattr(self.db, "list_delegate_finance_excluded_inbounds", None)
        remain_loader = getattr(self.db, "list_delegate_finance_exclude_client_remaining", None)
        current: int | None = actor_user_id
        seen: set[int] = set()
        while current is not None and current not in seen:
            seen.add(current)
            if inbound_loader is not None:
                try:
                    excluded_inbounds |= await inbound_loader(current)
                except Exception:
                    pass
            if remain_loader is not None:
                try:
                    exclude_remaining_keys |= await remain_loader(current)
                except Exception:
                    pass
            delegated_loader = getattr(self.db, "get_delegated_admin_by_user_id", None)
            if delegated_loader is None:
                break
            row = await delegated_loader(current)
            if row is None:
                break
            parent = int(row.get("parent_user_id") or 0)
            if parent <= 0 or parent == current:
                break
            current = parent
        return excluded_inbounds, exclude_remaining_keys

    async def _accumulate_scope_financial_ledger(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
        owner_id_set: set[str],
    ) -> ScopeFinancialLedger:
        seen: set[tuple[int, int, str]] = set()
        clients_count = 0
        allocated_bytes = 0
        consumed_bytes = 0
        remaining_bytes = 0
        panel_total_consumed_bytes = 0
        root_created_consumed_bytes = 0
        billable_segment_consumed_bytes = 0
        root_admin_id_set = {str(admin_id) for admin_id in settings.admin_ids}
        excluded_inbounds, exclude_remaining_keys = await self._merged_delegate_finance_exclusions_for_actor(
            actor_user_id=actor_user_id
        )
        for panel in await self.panel_service.list_panels():
            panel_id = int(panel["id"])
            moaf_exempt_for_scope: set[tuple[int, str]] = set()
            exemptions_loader = getattr(self.db, "list_moaf_client_exemptions_for_panel", None)
            if exemptions_loader is not None:
                try:
                    raw_ex = await exemptions_loader(panel_id)
                    for (ex_in_id, ex_uuid), meta in raw_ex.items():
                        if str(meta.get("owner_user_id") or "") in owner_id_set:
                            moaf_exempt_for_scope.add((int(ex_in_id), str(ex_uuid)))
                except Exception:
                    moaf_exempt_for_scope = set()
            segment_loader = getattr(self.db, "list_moaf_client_traffic_segments_for_panel", None)
            segments_by_key = await segment_loader(panel_id) if segment_loader is not None else {}
            resume_loader = getattr(self.db, "list_moaf_resume_delegate_caps_for_panel", None)
            resume_caps: dict[tuple[int, str, int], int] = {}
            if resume_loader is not None:
                try:
                    resume_caps = dict(await resume_loader(panel_id))
                except Exception:
                    resume_caps = {}
            try:
                inbounds = await self.panel_service.list_inbounds(panel_id)
            except Exception:
                continue
            for inbound in inbounds:
                inbound_id = int(inbound.get("id") or 0)
                if inbound_id <= 0 or (panel_id, inbound_id) in excluded_inbounds:
                    continue
                settings_raw = inbound.get("settings")
                settings_obj: dict[str, Any] = {}
                if isinstance(settings_raw, str) and settings_raw.strip():
                    try:
                        parsed = json.loads(settings_raw)
                        if isinstance(parsed, dict):
                            settings_obj = parsed
                    except Exception:
                        settings_obj = {}
                clients = settings_obj.get("clients") if isinstance(settings_obj.get("clients"), list) else []
                uuid_to_comment: dict[str, str] = {}
                for client in clients:
                    if isinstance(client, dict):
                        cu = str(client.get("id") or client.get("uuid") or "").strip()
                        if cu:
                            uuid_to_comment[cu] = str(client.get("comment") or "").strip()
                stats_by_uuid: dict[str, dict[str, int]] = {}
                for stat in inbound.get("clientStats") or []:
                    if not isinstance(stat, dict):
                        continue
                    stat_uuid = str(stat.get("uuid") or stat.get("id") or "").strip()
                    if not stat_uuid:
                        continue
                    stats_by_uuid[stat_uuid] = {
                        "used": max(0, int(stat.get("up") or 0)) + max(0, int(stat.get("down") or 0)),
                        "total": max(0, int(stat.get("total") or 0)),
                    }
                if stats_by_uuid:
                    panel_sum = 0
                    for stat_uuid, usage in stats_by_uuid.items():
                        cmt = uuid_to_comment.get(stat_uuid, "")
                        if _delegate_finance_client_out_of_scope(
                            panel_id=panel_id,
                            inbound_id=inbound_id,
                            client_uuid=stat_uuid,
                            comment=cmt,
                            owner_id_set=owner_id_set,
                            exclude_remaining_keys=exclude_remaining_keys,
                            moaf_exempt_for_scope=moaf_exempt_for_scope,
                        ):
                            continue
                        panel_sum += int(usage.get("used") or 0)
                    panel_total_consumed_bytes += panel_sum
                elif "up" in inbound or "down" in inbound:
                    panel_total_consumed_bytes += max(0, int(inbound.get("up") or 0)) + max(0, int(inbound.get("down") or 0))
                for client in clients:
                    if not isinstance(client, dict):
                        continue
                    client_uuid = str(client.get("id") or client.get("uuid") or "").strip()
                    if not client_uuid:
                        continue
                    comment = str(client.get("comment") or "").strip()
                    usage = stats_by_uuid.get(client_uuid, {"used": 0, "total": 0})
                    client_used_bytes = max(0, int(usage.get("used") or 0))
                    fin_tag = _delegate_finance_comment_tag(comment)
                    comment_owner_id = _owner_id_from_comment(comment)
                    if _delegate_finance_client_out_of_scope(
                        panel_id=panel_id,
                        inbound_id=inbound_id,
                        client_uuid=client_uuid,
                        comment=comment,
                        owner_id_set=owner_id_set,
                        exclude_remaining_keys=exclude_remaining_keys,
                        moaf_exempt_for_scope=moaf_exempt_for_scope,
                    ):
                        continue
                    key = (panel_id, inbound_id, client_uuid)
                    segments = _valid_report_segments(
                        segments=segments_by_key.get((inbound_id, client_uuid), []),
                        comment=comment,
                        root_admin_id_set=root_admin_id_set,
                    )
                    counted_as_root_created = False
                    if comment == "" or comment in root_admin_id_set:
                        root_created_consumed_bytes += int(usage.get("used") or 0)
                        counted_as_root_created = True
                    if segments:
                        if not counted_as_root_created:
                            root_created_consumed_bytes += int(usage.get("used") or 0)
                        client_total_bytes = max(0, int(client.get("totalGB") or 0))
                        count, billable_total_bytes, billable_used_bytes, billable_remaining_bytes = _billable_segment_totals(
                            segments=segments,
                            owner_id_set=owner_id_set,
                            current_total_bytes=client_total_bytes,
                            used_bytes=client_used_bytes,
                        )
                        if count <= 0 or key in seen:
                            continue
                        seen.add(key)
                        clients_count += count
                        allocated_bytes += billable_total_bytes
                        consumed_bytes += billable_used_bytes
                        billable_segment_consumed_bytes += billable_used_bytes
                        remaining_bytes += billable_remaining_bytes
                        continue
                    if comment == "" or comment in root_admin_id_set or str(comment_owner_id or "") not in owner_id_set or key in seen:
                        continue
                    seen.add(key)
                    client_total_bytes = max(0, int(client.get("totalGB") or 0))
                    if fin_tag == "moafresume" and comment_owner_id is not None:
                        delegate_uid = int(comment_owner_id)
                        cap_key = (inbound_id, client_uuid, delegate_uid)
                        cap = resume_caps.get(cap_key)
                        if cap is None:
                            insert_fn = getattr(self.db, "insert_moaf_resume_delegate_cap_if_missing", None)
                            get_fn = getattr(self.db, "get_moaf_resume_delegate_cap", None)
                            if insert_fn is not None:
                                await insert_fn(
                                    panel_id=panel_id,
                                    inbound_id=inbound_id,
                                    client_uuid=client_uuid,
                                    delegate_user_id=delegate_uid,
                                    cap_total_bytes=client_total_bytes,
                                )
                            if get_fn is not None:
                                cap = await get_fn(
                                    panel_id=panel_id,
                                    inbound_id=inbound_id,
                                    client_uuid=client_uuid,
                                    delegate_user_id=delegate_uid,
                                )
                            cap = cap if cap is not None else client_total_bytes
                            resume_caps[cap_key] = cap
                        effective_total = min(int(cap), client_total_bytes)
                        clients_count += 1
                        allocated_bytes += effective_total
                        remaining_bytes += max(0, effective_total - client_used_bytes)
                        consumed_bytes += client_used_bytes
                        continue
                    clients_count += 1
                    allocated_bytes += client_total_bytes
                    consumed_bytes += client_used_bytes
                    if client_total_bytes > 0:
                        remaining_bytes += max(client_total_bytes - client_used_bytes, 0)
        return ScopeFinancialLedger(
            clients_count=clients_count,
            allocated_bytes=allocated_bytes,
            consumed_bytes=consumed_bytes,
            remaining_bytes=remaining_bytes,
            panel_total_consumed_bytes=panel_total_consumed_bytes,
            root_created_consumed_bytes=root_created_consumed_bytes,
            billable_segment_consumed_bytes=billable_segment_consumed_bytes,
        )

    async def get_admin_scope_financial_summary(
        self,
        *,
        actor_user_id: int,
        settings: Settings,
    ) -> dict[str, Any]:
        wallet = await self.financial_service.get_wallet(actor_user_id) if self.financial_service is not None else {
            "balance": 0,
            "currency": "تومان",
        }
        pricing = await self.financial_service.get_pricing(actor_user_id) if self.financial_service is not None else {
            "price_per_gb": 0,
            "price_per_day": 0,
            "currency": "تومان",
            "charge_basis": "allocated",
            "apply_price_to_past_reports": 1,
        }
        delegated_loader = getattr(self.db, "get_delegated_admin_by_user_id", None)
        delegated = await delegated_loader(actor_user_id) if delegated_loader is not None else None
        is_primary_delegate = delegated is not None and int(delegated.get("parent_user_id") or 0) == 0
        owner_ids = await self.financial_scope_user_ids(actor_user_id=actor_user_id, settings=settings)
        if not owner_ids:
            return {
                "wallet": wallet,
                "pricing": pricing,
                "clients_count": 0,
                "allocated_bytes": 0,
                "consumed_bytes": 0,
                "remaining_bytes": 0,
                "allocated_gb": 0,
                "consumed_gb": 0,
                "remaining_gb": 0,
                "sale_amount": 0,
                "debt_amount": 0,
                "remaining_amount": 0,
                "total_transactions": 0,
                "scope_user_ids": [],
            }
        owner_id_set = {str(owner_id) for owner_id in owner_ids}
        ledger = await self._accumulate_scope_financial_ledger(
            actor_user_id=actor_user_id,
            settings=settings,
            owner_id_set=owner_id_set,
        )
        allocated_bytes = ledger.allocated_bytes
        consumed_bytes = ledger.consumed_bytes
        remaining_bytes = ledger.remaining_bytes
        price_per_gb = int(pricing.get("price_per_gb") or 0)
        allocated_gb = allocated_bytes // (1024 ** 3) + (1 if allocated_bytes % (1024 ** 3) else 0)
        gb_unit = 1024 ** 3
        charge_basis = str(pricing.get("charge_basis") or "allocated")
        excluded_inbounds, _ = await self._merged_delegate_finance_exclusions_for_actor(actor_user_id=actor_user_id)
        if charge_basis == "consumed" and is_primary_delegate:
            consumed_bytes = max(0, ledger.panel_total_consumed_bytes)
        consumed_gb = float(consumed_bytes) / float(gb_unit) if consumed_bytes > 0 else 0.0
        remaining_gb = float(remaining_bytes) / float(gb_unit) if remaining_bytes > 0 else 0.0
        scope_totals = (
            await self.financial_service.get_scope_sales_totals(
                owner_ids,
                excluded_inbound_pairs=excluded_inbounds if excluded_inbounds else None,
            )
            if self.financial_service is not None
            else {"total_sales": 0, "total_transactions": 0}
        )
        sale_amount = int(scope_totals.get("total_sales") or 0)
        if charge_basis == "consumed":
            debt_calculator = getattr(self.financial_service, "consumed_basis_debt_amount", None) if self.financial_service is not None else None
            debt_amount = debt_calculator(consumed_bytes=consumed_bytes, pricing=pricing) if debt_calculator is not None else (consumed_bytes * price_per_gb) // gb_unit
        else:
            debt_amount = allocated_gb * price_per_gb
        remaining_amount = (remaining_bytes * price_per_gb) // gb_unit
        return {
            "wallet": wallet,
            "pricing": pricing,
            "clients_count": ledger.clients_count,
            "allocated_bytes": allocated_bytes,
            "consumed_bytes": consumed_bytes,
            "remaining_bytes": remaining_bytes,
            "allocated_gb": allocated_gb,
            "consumed_gb": consumed_gb,
            "remaining_gb": remaining_gb,
            "sale_amount": sale_amount,
            "debt_amount": debt_amount,
            "remaining_amount": remaining_amount,
            "total_transactions": int(scope_totals.get("total_transactions") or 0),
            "scope_user_ids": owner_ids,
        }
