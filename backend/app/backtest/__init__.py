"""回测引擎包（Phase 4）。

引擎可插拔：``native``（自研事件驱动，默认）与 ``backtrader``（预留适配器）共同实现
``base.BacktestEngine``。数据层 ``data`` 提供后复权(HFQ)日线与交易日历。
"""
