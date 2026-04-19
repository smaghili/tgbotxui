from aiogram.fsm.state import State, StatesGroup


class AddPanelStates(StatesGroup):
    waiting_name = State()
    waiting_login_url = State()
    waiting_username = State()
    waiting_password = State()
    waiting_two_factor_choice = State()
    waiting_two_factor_code = State()


class BindServiceStates(StatesGroup):
    waiting_panel_select = State()
    waiting_telegram_user_id = State()
    waiting_client_email = State()
    waiting_service_name = State()


class InboundsListStates(StatesGroup):
    waiting_panel_select = State()
    waiting_overview_panel_select = State()


class ClientManageStates(StatesGroup):
    waiting_custom_expiry_days = State()
    waiting_custom_traffic_gb = State()
    waiting_custom_ip_limit = State()
    waiting_tg_id = State()
    waiting_online_search_query = State()
    waiting_bulk_add_traffic_gb = State()
    waiting_bulk_add_expiry_days = State()


class AdminSettingsStates(StatesGroup):
    waiting_depleted_cleanup_hours = State()


class DelegatedAdminStates(StatesGroup):
    waiting_target = State()
    waiting_title = State()
    waiting_inbound_selection = State()


class ProvisioningStates(StatesGroup):
    waiting_create_email = State()
    waiting_create_traffic_gb = State()
    waiting_create_expiry_days = State()
    waiting_create_tg_id_choice = State()
    waiting_create_tg_id = State()
    waiting_edit_tg_id = State()
    waiting_vless_config = State()
    waiting_edit_search_panel = State()
    waiting_edit_add_traffic_gb = State()
    waiting_edit_add_expiry_days = State()
