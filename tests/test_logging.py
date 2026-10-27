from checkit.logging_util import Logger, LogEvent


def test_levels_and_history():
    events = []
    log = Logger(sink=events.append, verbose=True)
    log.debug("d")
    log.info("i")
    log.warning("w")
    log.error("e")
    assert [e.level for e in events] == ["debug", "info", "warning", "error"]
    assert len(log.history) == 4


def test_debug_hidden_unless_verbose():
    events = []
    log = Logger(sink=events.append, verbose=False)
    log.debug("hidden")
    log.info("shown")
    assert [e.level for e in events] == ["info"]
    # but it is still recorded in history? No — emit returns early for
    # non-verbose debug. History only gets what was emitted.
    assert all(e.level != "debug" for e in log.history)


def test_verbose_enables_debug():
    events = []
    log = Logger(sink=events.append, verbose=True)
    log.debug("shown")
    assert events[0].level == "debug"


def test_percent_is_carried():
    log = Logger(sink=lambda e: None, verbose=True)
    ev = log.info("halfway", 50)
    assert ev.percent == 50
    assert ev.to_dict()["percent"] == 50
    assert ev.to_dict()["type"] == "log"


def test_set_verbose_toggles():
    events = []
    log = Logger(sink=events.append, verbose=False)
    log.set_verbose(True)
    log.debug("now visible")
    assert events[0].level == "debug"


def test_history_ring_buffer():
    log = Logger(sink=lambda e: None, verbose=True, history=5)
    for i in range(10):
        log.info(f"msg {i}")
    assert len(log.history) == 5
    assert log.history[-1].message == "msg 9"
    assert log.history[0].message == "msg 5"
