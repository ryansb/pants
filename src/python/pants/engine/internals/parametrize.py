# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Iterator

from pants.build_graph.address import BANNED_CHARS_IN_PARAMETERS
from pants.engine.addresses import Address
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class Parametrize:
    """A builtin function/dataclass that can be used to parametrize Targets.

    Parametrization is applied between TargetAdaptor construction and Target instantiation, which
    means that individual Field instances need not be aware of it.
    """

    args: tuple[str, ...]
    kwargs: dict[str, Any]

    def __init__(self, *args: str, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def to_parameters(self) -> dict[str, Any]:
        """Validates and returns a mapping from aliases to parameter values.

        This conversion is executed lazily to allow for more context in error messages, such as the
        TargetAdaptor consuming the Parametrize instance.
        """
        parameters = dict(self.kwargs)
        for arg in self.args:
            if not isinstance(arg, str):
                raise Exception(
                    f"In {self}:\n  Positional arguments must be strings, but "
                    f"`{arg}` was a `{type(arg).__name__}`."
                )
            previous_arg = parameters.get(arg)
            if previous_arg is not None:
                raise Exception(
                    f"In {self}:\n  Positional arguments cannot have the same name as "
                    f"keyword arguments. `{arg}` was also defined as `{arg}={previous_arg}`."
                )
            banned_chars = BANNED_CHARS_IN_PARAMETERS & set(arg)
            if banned_chars:
                raise Exception(
                    f"In {self}:\n  Positional argument `{arg}` contained separator characters "
                    f"(`{'`,`'.join(banned_chars)}`).\n\n"
                    "To use `{arg}` as a parameter, you can pass it as a keyword argument to "
                    "give it an alias. For example: `parametrize(short_memorable_name='{arg}')`"
                )
            parameters[arg] = arg
        return parameters

    @classmethod
    def expand(
        cls, address: Address, fields: dict[str, Any | Parametrize]
    ) -> Iterator[tuple[Address, dict[str, Any]]]:
        """Produces the cartesian product of fields for the given possibly-Parametrized fields.

        Only one level of expansion is performed: if individual field values might also contain
        Parametrize instances (in particular: an `overrides` field), expanding those will require
        separate calls.
        """
        try:
            parametrized: list[list[tuple[str, str, Any]]] = [
                [
                    (field_name, alias, field_value)
                    for alias, field_value in v.to_parameters().items()
                ]
                for field_name, v in fields.items()
                if isinstance(v, Parametrize)
            ]
        except Exception as e:
            raise Exception(f"Failed to parametrize `{address}`:\n{e}") from e

        if not parametrized:
            yield (address, fields)
            return

        non_parametrized = [
            (field_name, field_value)
            for field_name, field_value in fields.items()
            if not isinstance(field_value, Parametrize)
        ]

        for parametrized_args in itertools.product(*parametrized):
            expanded_address = address.parametrize(
                {field_name: alias for field_name, alias, _ in parametrized_args}
            )
            expanded_fields: dict[str, Any] = dict(
                (
                    *non_parametrized,
                    *(
                        (field_name, field_value)
                        for field_name, _, field_value in parametrized_args
                    ),
                )
            )
            yield (expanded_address, expanded_fields)

    def __repr__(self) -> str:
        strs = [str(s) for s in self.args]
        strs.extend(f"{alias}={value}" for alias, value in self.kwargs.items())
        return f"parametrize({', '.join(strs)}"
