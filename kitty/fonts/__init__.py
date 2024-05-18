from enum import Enum, IntEnum, auto
from typing import TYPE_CHECKING, Dict, List, Literal, NamedTuple, Sequence, Tuple, TypedDict, TypeVar, Union

from kitty.types import run_once
from kitty.typing import CoreTextFont, FontConfigPattern

if TYPE_CHECKING:
    import re


class ListedFont(TypedDict):
    family: str
    style: str
    full_name: str
    postscript_name: str
    is_monospace: bool
    is_variable: bool
    descriptor: Union[FontConfigPattern, CoreTextFont]


class VariableAxis(TypedDict):
    minimum: float
    maximum: float
    default: float
    hidden: bool
    tag: str
    strid: str  # Can be empty string when not present


class NamedStyle(TypedDict):
    axis_values: Dict[str, float]
    name: str
    psname: str  # can be empty string when not present


class DesignValue1(TypedDict):
    format: Literal[1]
    flags: int
    name: str
    value: float


class DesignValue2(TypedDict):
    format: Literal[2]
    flags: int
    name: str
    value: float
    minimum: float
    maximum: float


class DesignValue3(TypedDict):
    format: Literal[3]
    flags: int
    name: str
    value: float
    linked_value: float


DesignValue = Union[DesignValue1, DesignValue2, DesignValue3]


class DesignAxis(TypedDict):
    name: str
    ordering: int
    tag: str
    values: List[DesignValue]


class AxisValue(TypedDict):
    design_index: int
    value: float


class MultiAxisStyle(TypedDict):
    flags: int
    name: str
    values: Tuple[AxisValue, ...]


class VariableData(TypedDict):
    axes: Tuple[VariableAxis, ...]
    named_styles: Tuple[NamedStyle, ...]
    variations_postscript_name_prefix: str
    elided_fallback_name: str
    design_axes: Tuple[DesignAxis, ...]
    multi_axis_styles: Tuple[MultiAxisStyle, ...]


class FontFeature:

    __slots__ = 'name', 'parsed'

    def __init__(self, name: str, parsed: bytes):
        self.name = name
        self.parsed = parsed

    def __repr__(self) -> str:
        return repr(self.name)


class ModificationType(Enum):
    underline_position = auto()
    underline_thickness = auto()
    strikethrough_position = auto()
    strikethrough_thickness = auto()
    cell_width = auto()
    cell_height = auto()
    baseline = auto()
    size = auto()


class ModificationUnit(IntEnum):
    pt = 0
    percent = 1
    pixel = 2


class ModificationValue(NamedTuple):
    val: float
    unit: ModificationUnit

    def __repr__(self) -> str:
        u = '%' if self.unit is ModificationUnit.percent else ''
        return f'{self.val:g}{u}'


class FontModification(NamedTuple):
    mod_type: ModificationType
    mod_value: ModificationValue
    font_name: str = ''

    def __repr__(self) -> str:
        fn = f' {self.font_name}' if self.font_name else ''
        return f'{self.mod_type.name}{fn} {self.mod_value}'


class FontSpec(NamedTuple):
    family: str = ''
    style: str = ''
    postscript_name: str = ''
    full_name: str = ''
    system: str = ''
    axes: Tuple[Tuple[str, float], ...] = ()
    variable_name: str = ''
    created_from_string: str = ''

    @property
    def is_system(self) -> bool:
        return bool(self.system)

    @property
    def is_auto(self) -> bool:
        return self.system == 'auto'


Descriptor = Union[FontConfigPattern, CoreTextFont]
DescriptorVar = TypeVar('DescriptorVar', FontConfigPattern, CoreTextFont, Descriptor)

class Scorer:

    def __init__(self, bold: bool = False, italic: bool = False, monospaced: bool = True, prefer_variable: bool = False) -> None:
        self.bold = bold
        self.italic = italic
        self.monospaced = monospaced
        self.prefer_variable = prefer_variable

    def sorted_candidates(self, candidates: Sequence[DescriptorVar], dump: bool = False) -> List[DescriptorVar]:
        raise NotImplementedError()

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(bold={self.bold}, italic={self.italic}, monospaced={self.monospaced}, prefer_variable={self.prefer_variable})'
    __str__ = __repr__


@run_once
def fnname_pat() -> 're.Pattern[str]':
    import re
    return re.compile(r'\s+')


def family_name_to_key(family: str) -> str:
    return fnname_pat().sub(' ', family).strip().lower()
