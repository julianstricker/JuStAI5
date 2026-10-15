from justai.auth.throttle import LoginThrottle


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_blocks_after_free_attempts_and_backs_off() -> None:
    clock = Clock()
    th = LoginThrottle(free_attempts=3, base_block_s=10, max_block_s=60, clock=clock)
    for _ in range(2):
        th.failure("user:a", "ip:1")
        assert th.retry_after("user:a", "ip:1") == 0
    th.failure("user:a", "ip:1")
    assert th.retry_after("user:a") == 10
    clock.t += 10
    th.failure("user:a")
    assert th.retry_after("user:a") == 20  # doubles
    for _ in range(5):
        th.failure("user:a")
    assert th.retry_after("user:a") == 60  # capped
    # Another user from another address is not affected.
    assert th.retry_after("user:b", "ip:2") == 0


def test_success_resets_user_but_not_address() -> None:
    clock = Clock()
    th = LoginThrottle(free_attempts=1, base_block_s=5, clock=clock)
    th.failure("user:a", "ip:1")
    th.success("user:a")
    assert th.retry_after("user:a") == 0
    assert th.retry_after("ip:1") == 5


def test_window_expiry_forgets_old_failures() -> None:
    clock = Clock()
    th = LoginThrottle(free_attempts=2, window_s=60, clock=clock)
    th.failure("user:a")
    clock.t += 61
    th.failure("user:a")
    assert th.retry_after("user:a") == 0
