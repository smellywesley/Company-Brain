"""Executor registry seam (executors themselves tested in their own files)."""

import asyncio

from app.services.executors.registry import ExecutorRegistry, load_executors


def test_register_and_build():
    @ExecutorRegistry.register("dummy_action")
    async def _dummy(params: dict) -> dict:
        return {"status": "ok", "tenant": params.get("_tenant_id")}

    built = ExecutorRegistry.build()
    assert "dummy_action" in built
    out = asyncio.run(built["dummy_action"]({"_tenant_id": "t1"}))
    assert out == {"status": "ok", "tenant": "t1"}


def test_load_executors_is_graceful_when_modules_absent():
    # The listed executor modules may not exist yet — must not raise.
    built = load_executors()
    assert isinstance(built, dict)
