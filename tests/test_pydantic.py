from pydantic import BaseModel

from safe_mapper.safe_mapper import map_to, safe_mapper


class Bar(BaseModel):
    x: int
    y: str


def test_simple_pydantic_mapper():
    @safe_mapper(Bar)
    class Foo(BaseModel):
        x: int
        y: str

    foo = Foo(x=42, y="answer")
    bar = Bar(x=42, y="answer")
    assert map_to(foo, Bar) == bar


class Baz(BaseModel):
    bar: Bar


def test_recursive_pydantic_mapper():
    @safe_mapper(Bar)
    class Bar2(BaseModel):
        x: int
        y: str

    @safe_mapper(Baz)
    class Baz2(BaseModel):
        bar: Bar2

    data: dict = {"bar": {"x": 42, "y": "answer"}}
    assert repr(map_to(Baz2(**data), Baz)) == repr(Baz(**data))
