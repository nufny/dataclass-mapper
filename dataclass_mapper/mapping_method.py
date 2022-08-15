from enum import Enum, auto
from inspect import isfunction, signature
from typing import Any, Callable, Union, cast, get_args, get_origin
from uuid import uuid4

from .classmeta import ClassMeta, DataclassType
from .fieldmeta import FieldMeta


class Other(Enum):
    USE_DEFAULT = auto()


# the different types that can be used as origin (source) for mapping to a member
# - str: the name of a different variable in the original class
# - Callable: a function that produces the value (can use `self` as parameter)
# - Other.USE_DEFAULT: Don't map to this variable (only allowed if there is a default value/factory for it)
Origin = Union[str, Callable, Other]
StringFieldMapping = dict[str, Origin]


class MappingMethodSourceCode:
    """Source code of the mapping method"""

    def __init__(self, source_cls: ClassMeta, target_cls: ClassMeta) -> None:
        self.source_cls = source_cls
        self.target_cls = target_cls
        self.lines = [
            f'def convert(self) -> "{self.target_cls.name}":',
            f"    d = {{}}",
        ]
        self.methods: dict[str, Callable] = {}

    def get_source(self, name: str) -> str:
        return f"self.{name}"

    def _add_line(self, left_side: str, right_side: str, indent=4) -> None:
        self.lines.append(f'{" "*indent}d["{left_side}"] = {right_side}')

    def add_assignment(
        self,
        target: FieldMeta,
        source: FieldMeta,
        only_if_not_None: bool = False,
        only_if_set: bool = False,
    ) -> None:
        source_var_name = f"self.{source.name}"
        indent = 4
        if only_if_not_None:
            self.lines.append(f"    if {source_var_name} is not None:")
            indent = 8
        if only_if_set:
            self.lines.append(f"    if '{source.name}' in self.__fields_set__:")
            indent = 8
        self._add_line(target.name, source_var_name, indent)

    def _get_map_func(self, name: str, target_cls: Any) -> str:
        func_name = get_map_to_func_name(target_cls)
        return f"{name}.{func_name}()"

    def is_mappable_to(self, SourceCls, TargetCls) -> bool:
        func_name = get_map_to_func_name(TargetCls)
        return hasattr(SourceCls, func_name)

    def add_recursive(
        self,
        target: FieldMeta,
        source: FieldMeta,
        only_if_set: bool = False,  # both are optional, we should only set them if they have value
        if_None: bool = False,  # source can be Optional, so add None checker
    ) -> None:
        source_var_name = f"self.{source.name}"

        right_side = self._get_map_func(source_var_name, target_cls=target.type)

        if only_if_set:
            self.lines.append(f"    if '{source.name}' in self.__fields_set__:")
            indent = 8
            if if_None:
                right_side = f"None if {source_var_name} is None else {right_side}"
            self._add_line(target.name, right_side, indent)
        else:
            if if_None:
                right_side = f"None if {source_var_name} is None else {right_side}"
            self._add_line(target.name, right_side)

    def add_recursive_list(
        self,
        target: FieldMeta,
        source: FieldMeta,
        if_None: bool = False,
        only_if_not_None: bool = False,
        only_if_set: bool = False,
    ) -> None:
        source_var_name = f"self.{source.name}"
        list_item_type = get_args(target.type)[0]
        right_side = (
            f'[{self._get_map_func("x", target_cls=list_item_type)} for x in {source_var_name}]'
        )

        indent = 4
        if only_if_not_None:
            self.lines.append(f"    if {source_var_name} is not None:")
            indent = 8
        if only_if_set:
            self.lines.append(f"    if '{source.name}' in self.__fields_set__:")
            indent = 8

        if if_None:
            right_side = f"None if {source_var_name} is None else {right_side}"
        self._add_line(target.name, right_side, indent)

    def add_function_call(self, target: FieldMeta, function: Callable) -> None:
        name = f"_{uuid4().hex}"
        if len(signature(function).parameters) == 0:
            self.methods[name] = cast(Callable, staticmethod(function))
        else:
            # already a method
            # TODO assert that there is only one parameter and that it is `self`
            self.methods[name] = function
        source = self.get_source(name)
        self._add_line(target.name, f"{source}()")

    def add_mapping(self, target: FieldMeta, source: Union[FieldMeta, Callable]) -> None:
        if isfunction(source):
            self.add_function_call(target, source)
        else:
            assert isinstance(source, FieldMeta)

            # same type, just assign it
            if target.type == source.type and not (source.allow_none and target.disallow_none):
                if (
                    source.allow_none
                    and target.allow_none
                    and not target.required
                    and self.source_cls._type == self.target_cls._type == DataclassType.PYDANTIC
                ):
                    # maintain Pydantic's unset property
                    self.add_assignment(target=target, source=source, only_if_set=True)
                else:
                    self.add_assignment(target=target, source=source)

            # allow optional to non-optional if setting the target is not required (because of an default value)
            elif (
                target.type == source.type
                and source.allow_none
                and target.disallow_none
                and not target.required
            ):
                self.add_assignment(target=target, source=source, only_if_not_None=True)

            # different type, but also safe mappable
            # with optional
            elif self.is_mappable_to(source.type, target.type) and not (
                source.allow_none and target.disallow_none
            ):
                if (
                    source.allow_none
                    and target.allow_none
                    and not target.required
                    and self.source_cls._type == self.target_cls._type == DataclassType.PYDANTIC
                ):
                    # maintain Pydantic's unset property
                    self.add_recursive(target=target, source=source, if_None=True, only_if_set=True)
                else:
                    self.add_recursive(target=target, source=source, if_None=source.allow_none)

            # both are lists of safe mappable types
            # with optional
            elif (
                get_origin(source.type) is list
                and get_origin(target.type) is list
                and self.is_mappable_to(get_args(source.type)[0], get_args(target.type)[0])
                and not (source.allow_none and target.disallow_none)
            ):
                if (
                    source.allow_none
                    and target.allow_none
                    and not target.required
                    and self.source_cls._type == self.target_cls._type == DataclassType.PYDANTIC
                ):
                    self.add_recursive_list(
                        target=target,
                        source=source,
                        if_None=source.allow_none,
                        only_if_set=True,
                    )
                else:
                    self.add_recursive_list(target=target, source=source, if_None=source.allow_none)

            # allow optional to non-optional if setting the target is not required (because of an default value)
            elif (
                get_origin(source.type) is list
                and get_origin(target.type) is list
                and self.is_mappable_to(get_args(source.type)[0], get_args(target.type)[0])
                and source.allow_none
                and target.disallow_none
                and not target.required
            ):
                self.add_recursive_list(
                    target=target, source=source, if_None=source.allow_none, only_if_not_None=True
                )

            # impossible
            else:
                raise TypeError(
                    f"{source} of '{self.source_cls.name}' cannot be converted to {target}"
                )

    def __str__(self) -> str:
        return_statement = f"    return {self.target_cls.alias_name}(**d)"
        return "\n".join(self.lines + [return_statement])


def get_map_to_func_name(cls: Any) -> str:
    return f"_map_to_{cls.__name__}"
