"""Redis scheduler lease and deterministic leadership transitions."""

from __future__ import annotations

from app.services.scheduler_leader import RedisLease, SchedulerLeader


class FakeRedis:
    def __init__(self):
        self.acquire = True
        self.script_results = [1, 1]
        self.set_calls: list[tuple] = []

    def set(self, key, value, nx=False, ex=None):
        self.set_calls.append((key, value, nx, ex))
        return self.acquire

    def register_script(self, _script):
        return lambda **_kwargs: self.script_results.pop(0)


def test_redis_lease_uses_owned_token_for_acquire_renew_release():
    client = FakeRedis()
    lease = RedisLease(client, "scheduler-key", ttl_seconds=30, token="owner-1")

    assert lease.try_acquire() is True
    assert client.set_calls == [("scheduler-key", "owner-1", True, 30)]
    assert lease.renew() is True
    assert lease.release() is True


def test_scheduler_leader_starts_and_stops_scheduler_on_lease_transition():
    events: list[str] = []
    lease = FakeRedisLease()
    leader = SchedulerLeader(
        lease,
        on_acquired=lambda: events.append("start"),
        on_lost=lambda: events.append("stop"),
        renew_seconds=1,
    )

    leader.tick()
    assert leader.is_leader is True
    lease.renewed = False
    leader.tick()

    assert leader.is_leader is False
    assert events == ["start", "stop"]


def test_scheduler_leader_stops_scheduler_when_renewal_errors():
    events: list[str] = []
    lease = FakeRedisLease()
    leader = SchedulerLeader(
        lease,
        on_acquired=lambda: events.append("start"),
        on_lost=lambda: events.append("stop"),
        renew_seconds=1,
    )
    leader.tick()
    lease.raise_on_renew = True

    leader.tick()

    assert leader.is_leader is False
    assert events == ["start", "stop"]


class FakeRedisLease:
    def __init__(self):
        self.acquired = True
        self.renewed = True
        self.released = False
        self.raise_on_renew = False

    def try_acquire(self):
        return self.acquired

    def renew(self):
        if self.raise_on_renew:
            raise ConnectionError("redis down")
        return self.renewed

    def release(self):
        self.released = True
        return True
