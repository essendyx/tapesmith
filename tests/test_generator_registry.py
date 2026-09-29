import sys
import types

import pytest

from tapesmith.document.generators import GENERATORS, GeneratorOutput, GeneratorRef, get_generator, run_generator
from tapesmith.document.model import LabelDocument


def test_get_generator_unknown_name_raises():
    with pytest.raises(ValueError, match="xyz"):
        get_generator("xyz")


def test_all_registered_generators_have_a_module_path():
    assert set(GENERATORS) == {"kabelfahne", "kabelwickel", "raster"}
    assert all(isinstance(path, str) for path in GENERATORS.values())


@pytest.fixture
def fake_generator_module(monkeypatch):
    calls = []

    def generate(params, values, profile):
        calls.append((dict(params), dict(values), profile))
        return GeneratorOutput(document=LabelDocument())

    module = types.ModuleType("tests_fake_gen")
    module.PARAMS = {"a": 1}
    module.generate = generate
    monkeypatch.setitem(sys.modules, "tests_fake_gen", module)
    monkeypatch.setitem(GENERATORS, "fake", "tests_fake_gen")
    return module, calls


def test_run_generator_merges_params_with_defaults(fake_generator_module):
    module, calls = fake_generator_module
    output = run_generator(GeneratorRef(name="fake", params={"a": 2}), {"host": "pmx10"}, profile="P")
    assert isinstance(output, GeneratorOutput)
    assert calls[0] == ({"a": 2}, {"host": "pmx10"}, "P")


def test_run_generator_unknown_param_raises(fake_generator_module):
    with pytest.raises(ValueError, match="unbekannte Parameter"):
        run_generator(GeneratorRef(name="fake", params={"c": 3}), {}, profile="P")


def test_get_generator_missing_module_raises(monkeypatch):
    monkeypatch.setitem(GENERATORS, "broken", "tapesmith.does_not_exist_module")
    with pytest.raises(ValueError, match="broken"):
        get_generator("broken")
