import pytest

from app.db import Database, normalize_name


def test_name_normalization():
    assert normalize_name("  Ангелина   КиселЁва ") == normalize_name("ангелина киселева")


@pytest.mark.asyncio
async def test_database_draw_is_saved_and_stable(tmp_path):
    database = Database(tmp_path / "santa.db")
    await database.init()
    game = await database.create_game(100, "Test", None, None)
    for user_id, name in [(1, "Аня"), (2, "Борис"), (3, "Вика"), (4, "Глеб")]:
        await database.add_participant(game["id"], user_id, name, None, None)

    rows = await database.draw(game["id"])
    assert len(rows) == 4
    first_result = await database.result(game["id"], 1)
    second_result = await database.result(game["id"], 1)
    assert first_result["name"] == second_result["name"]
    assert first_result["name"] != "Аня"

