from aiogram.fsm.state import State, StatesGroup


class CreateGame(StatesGroup):
    title = State()
    budget = State()
    exchange_date = State()


class JoinByCode(StatesGroup):
    code = State()


class Registration(StatesGroup):
    name = State()
    wish = State()
    photo = State()

