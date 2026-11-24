"""HookBus 测试（doc 21 §4.4）。"""

import unittest

from agent_service.orchestrator.hooks import HookBus, get_hook_bus


class TestHookBus(unittest.IsolatedAsyncioTestCase):
    """Hook 总线注册/触发/容错。"""

    def setUp(self) -> None:
        """每个用例独立建总线。"""
        self.bus = HookBus()

    async def test_register_and_emit_sync(self):
        """同步 handler 按注册顺序触发。"""
        order: list[str] = []

        def first(_event, _ctx):
            order.append("first")

        def second(_event, _ctx):
            order.append("second")

        self.bus.register("e1", first)
        self.bus.register("e1", second)
        await self.bus.emit("e1", {})
        self.assertEqual(order, ["first", "second"])

    async def test_emit_passes_ctx(self):
        """ctx 透传给 handler。"""
        received = {}

        def handler(event, ctx):
            received["ctx"] = ctx
            received["event"] = event

        self.bus.register("after_step", handler)
        ctx = {"run": object(), "status": "success"}
        await self.bus.emit("after_step", ctx)
        self.assertIs(received["ctx"], ctx)
        self.assertEqual(received["event"], "after_step")

    async def test_async_handler(self):
        """async handler 被 await。"""
        flag = {"called": False}

        async def handler(_event, _ctx):
            flag["called"] = True

        self.bus.register("e", handler)
        await self.bus.emit("e", {})
        self.assertTrue(flag["called"])

    async def test_exception_does_not_block_others(self):
        """handler 抛异常不阻断后续 handler。"""
        calls: list[str] = []

        def bad(_event, _ctx):
            calls.append("bad")
            raise RuntimeError("boom")

        def good(_event, _ctx):
            calls.append("good")

        self.bus.register("e", bad)
        self.bus.register("e", good)
        await self.bus.emit("e", {})  # 不应抛出
        self.assertEqual(calls, ["bad", "good"])

    async def test_no_handlers_is_noop(self):
        """无 handler 的事件 emit 为 no-op。"""
        await self.bus.emit("not_registered", {})

    def test_get_hook_bus_singleton(self):
        """进程级单例。"""
        self.assertIs(get_hook_bus(), get_hook_bus())

    async def test_count(self):
        """count 统计某事件 handler 数。"""

        def handler(_event, _ctx):
            pass

        self.bus.register("x", handler)
        self.bus.register("x", handler)  # 重复注册去重
        self.assertEqual(self.bus.count("x"), 1)
        self.bus.unregister("x", handler)
        self.assertEqual(self.bus.count("x"), 0)


if __name__ == "__main__":
    unittest.main()
