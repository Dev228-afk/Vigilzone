import logging

from src.logic.class_filter import resolve_class_filter


class DummyModel:
    def __init__(self, names):
        self.names = names


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_weapon_alias_matches_subclasses_without_warning():
    model = DummyModel({0: "handgun", 1: "kitchen_knife", 2: "person"})
    logger = logging.getLogger("test_class_filter_alias")
    logger.setLevel(logging.INFO)
    handler = _ListHandler()
    logger.handlers = [handler]

    allowed_ids, _ = resolve_class_filter(
        model,
        class_names=["weapon"],
        lane_name="weapon_yolo",
        logger=logger,
    )

    assert allowed_ids == {0, 1}
    warnings = [r for r in handler.records if r.levelno >= logging.WARNING]
    assert warnings == []


def test_class_filter_logs_error_on_true_miss():
    model = DummyModel({0: "person", 1: "car"})
    logger = logging.getLogger("test_class_filter_miss")
    logger.setLevel(logging.INFO)
    handler = _ListHandler()
    logger.handlers = [handler]

    allowed_ids, _ = resolve_class_filter(
        model,
        class_names=["weapon"],
        lane_name="weapon_yolo",
        logger=logger,
    )

    assert allowed_ids is None
    errors = [r for r in handler.records if r.levelno >= logging.ERROR]
    assert errors, "Expected an error log when no classes match"
