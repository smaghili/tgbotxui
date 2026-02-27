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


class ClientManageStates(StatesGroup):
    waiting_custom_expiry_days = State()
    waiting_custom_traffic_gb = State()
    waiting_custom_ip_limit = State()
    waiting_tg_id = State()
    waiting_online_search_query = State()
