"""Tests for the create-dpack TUI wizard."""

import pytest
from pathlib import Path

from textual.widgets import Checkbox

from dlab.create_dpack_wizard import (
    BasicsScreen,
    ContainerScreen,
    CreateDpackApp,
    DpackCheckbox,
    ModelScreen,
    PermissionsScreen,
    SkeletonsScreen,
    SkillSearchScreen,
    SummaryScreen,
)

PAUSE: float = 0.3


class TestBasicsScreen:
    """Tests for the first screen."""

    @pytest.mark.asyncio
    async def test_renders(self, tmp_path: Path) -> None:
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, BasicsScreen)
            app.screen.query_one("#name-input")
            app.screen.query_one("#desc-input")

    @pytest.mark.asyncio
    async def test_empty_name_blocked(self, tmp_path: Path) -> None:
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, BasicsScreen)

    @pytest.mark.asyncio
    async def test_valid_name_navigates(self, tmp_path: Path) -> None:
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#name-input").value = "test-dpack"
            await pilot.click("#next-btn")
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, ContainerScreen)

    @pytest.mark.asyncio
    async def test_existing_dpack_collision(self, tmp_path: Path) -> None:
        (tmp_path / "existing").mkdir()
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#name-input").value = "existing"
            await pilot.click("#next-btn")
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, BasicsScreen)
            assert app.screen.query_one("#overwrite-btn").display is True

    @pytest.mark.asyncio
    async def test_overwrite_allows_navigation(self, tmp_path: Path) -> None:
        (tmp_path / "existing").mkdir()
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#name-input").value = "existing"
            await pilot.click("#next-btn")
            await pilot.pause(delay=PAUSE)
            await pilot.click("#overwrite-btn")
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, ContainerScreen)


class TestNavigation:
    """Test forward and backward navigation."""

    @pytest.mark.asyncio
    async def test_back_from_container(self, tmp_path: Path) -> None:
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#name-input").value = "test"
            await pilot.click("#next-btn")
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, ContainerScreen)
            await pilot.click("#back-btn")
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, BasicsScreen)

    @pytest.mark.asyncio
    async def test_state_preserved_on_back(self, tmp_path: Path) -> None:
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#name-input").value = "my-dpack"
            app.screen.query_one("#desc-input").value = "My description"
            await pilot.click("#next-btn")
            await pilot.pause(delay=PAUSE)
            await pilot.click("#back-btn")
            await pilot.pause(delay=PAUSE)
            assert app.screen.query_one("#name-input").value == "my-dpack"
            assert app.screen.query_one("#desc-input").value == "My description"


class TestSkipSkillsScreen:
    """Test that skills screen is skipped when skills unchecked."""

    @pytest.mark.asyncio
    async def test_skills_unchecked_skips_to_summary(self, tmp_path: Path) -> None:
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#name-input").value = "test"
            await pilot.click("#next-btn")  # -> Container
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")  # -> Features
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")  # -> Model
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")  # -> Permissions
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")  # -> Skeletons
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, SkeletonsScreen)

            app.screen.query_one("#skel-skills", Checkbox).value = False
            await pilot.click("#next-btn")
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, SummaryScreen)


class TestDpackCheckbox:
    """Test custom checkbox widget."""

    @pytest.mark.asyncio
    async def test_checkbox_renders(self, tmp_path: Path) -> None:
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#name-input").value = "test"
            await pilot.click("#next-btn")  # -> Container
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")  # -> Features (has checkboxes)
            await pilot.pause(delay=PAUSE)
            checkboxes = list(app.screen.query(Checkbox))
            assert len(checkboxes) > 0
            assert isinstance(checkboxes[0], DpackCheckbox)


class TestModelScreen:
    """Test model selection screen."""

    @pytest.mark.asyncio
    async def test_renders_with_models(self, tmp_path: Path) -> None:
        app = CreateDpackApp(str(tmp_path))
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause(delay=PAUSE)
            app.screen.query_one("#name-input").value = "test"
            await pilot.click("#next-btn")  # -> Container
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")  # -> Features
            await pilot.pause(delay=PAUSE)
            await pilot.click("#next-btn")  # -> Model
            await pilot.pause(delay=PAUSE)
            assert isinstance(app.screen, ModelScreen)
            ol = app.screen.query_one("#model-results")
            assert ol is not None
