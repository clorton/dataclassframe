import pandas as pd
import numpy as np
from dataclasses import fields
from typing import Optional, List, Union, Type, TypeVar, Generic, Iterable
from copy import copy, deepcopy

RecordT = TypeVar("RecordT")


def to_basic_type(obj):
    if isinstance(obj, np.generic):
        return obj.item()
    else:
        return obj


class _IAtIndexer(Generic[RecordT]):
    def __init__(self, dcf: "DataClassFrame[RecordT]"):
        self.dcf = dcf

    def __getitem__(self, key: int) -> RecordT:
        row = self.dcf.df.iloc[key]

        if isinstance(row, pd.DataFrame):
            if len(row) > 1:
                raise KeyError("key combination is not unique. To slice use `iloc` method.")
            row = row.iloc[0]

        row = {k: to_basic_type(v) for k, v in row.to_dict().items()}
        row = self.dcf.record_class(**row)
        return row

    def __setitem__(self, key: int, value: RecordT):
        row = pd.Series(value.__dict__)
        self.dcf.df.iloc[key] = row


class _AtIndexer(Generic[RecordT]):
    def __init__(self, dcf: "DataClassFrame"):
        self.dcf = dcf

    def __getitem__(self, key) -> RecordT:
        idx = pd.IndexSlice
        row = self.dcf.df.loc[idx[key], :]

        if isinstance(row, pd.DataFrame):
            if len(row) > 1:
                raise KeyError("key combination is not unique. To slice use `loc` method.")
            row = row.iloc[0]

        row = {k: to_basic_type(v) for k, v in row.to_dict().items()}
        row = self.dcf.record_class(**row)
        return row

    def __setitem__(self, key, value: RecordT):
        # TODO: need to validate with multi indexing
        index_value_in_record = value.__dict__[self.dcf.index]
        if key != index_value_in_record:
            raise ValueError(
                "key {} must equal values in the record ({})".format(key, index_value_in_record))
        row = pd.Series(value.__dict__)
        self.dcf.df.loc[key] = row


class _ColumnsWrapper(object):
    def __init__(self, dcf: "DataClassFrame"):
        cols = set(dcf.df.columns)
        super().__setattr__('__dcf', dcf)
        super().__setattr__('__cols', cols)

    def __getattribute__(self, name) -> pd.Series:
        cols = super().__getattribute__('__cols')
        dcf = super().__getattribute__('__dcf')

        if name in cols:
            return dcf.df[name]
        else:
            return super().__getattribute__(name)

    def __setattr__(self, name, value):
        cols = super().__getattribute__('__cols')
        dcf = super().__getattribute__('__dcf')

        if name in cols:
            # TODO: verify data-type isn't changed
            dcf.df[name] = value
        else:
            super().__setattr__(name, value)


class DataClassFrame(Generic[RecordT]):
    def __init__(
            self,
            record_class: Type[RecordT],
            data: Iterable[RecordT],
            index: Union[None, str, List[str]] = None,
    ):
        """
        Container of dataclasses.

        Args:
            record_class: The dataclasses class of each record
            data: An iterable of dataclass records
            index: Fields of the dataclass to use as indexes
        """

        def validate_and_to_dict(i, dc):
            if not isinstance(dc, record_class):
                raise ValueError(
                    "All data must be of type {}. Found type {} at index {}".format(record_class, dc, i))
            return dc.__dict__

        df_data = [validate_and_to_dict(i, dc) for i, dc in enumerate(data)]
        if len(df_data) < 1:
            raise ValueError("Data must contain at least one record")
        df = self._dataclass_to_empty_dataframe(record_class)
        df = df.append(df_data)

        self._from_dataframe(record_class=record_class, data=df, index=index)

    @classmethod
    def from_dataframe(
            cls,
            record_class: Type[RecordT],
            data: Optional[pd.DataFrame] = None,
            index: Union[None, str, List[str]] = None,
    ):
        """
        Create a DataClassFrame using a Pandas DataFrame

        Args:
            record_class: The dataclasses class of each record
            data: A Pandas DataFrame of data
            index: Fields of the dataclass to use as indexes

        Returns: DataClassFrame

        """

        self = cls.__new__(cls)
        self._from_dataframe(record_class=record_class, data=data, index=index)
        return self

    def _from_dataframe(
            self,
            record_class: Type[RecordT],
            data: Optional[pd.DataFrame] = None,
            index: Union[None, str, List[str]] = None,
    ):
        self.record_class = record_class

        if data is not None:
            self.df = data
        else:
            self.df = self._dataclass_to_empty_dataframe(record_class)

        self.index = index
        if index is not None:
            self.df = self.df.set_index(index, drop=False, verify_integrity=True)
        else:
            self.df = self.df.reset_index(drop=True)

        self._cols = _ColumnsWrapper(self)

    @staticmethod
    def _dataclass_to_empty_dataframe(record_class: Type[RecordT]):
        """
        Convert dataclass class to a empty dataframe with matching columns
        """

        df = pd.DataFrame()
        for field in fields(record_class):
            try:
                df[field.name] = pd.Series(name=field.name, dtype=field.type)
            except TypeError:
                # If `TypeError` raised by `pandas_dtype` method. Just default to 'object' i.e. list
                df[field.name] = pd.Series(name=field.name, dtype='object')
        return df

    @property
    def iat(self) -> _IAtIndexer[RecordT]:
        """
        Access a single element using positional index.

        Returns: A record of type `RecordT`

        Examples:
            Access second element

            >>> self.iat[1]

            Access last element

            >>> self.iat[-1]

        """

        return _IAtIndexer(self)

    @property
    def at(self) -> _AtIndexer[RecordT]:
        """
        Access a single element using a dictionary like key(s). The key or key combination must
        index a unique record otherwise a `KeyError` is raised.

        Returns: A record of type `RecordT`

        Examples:
            Access element `'a'` using the first field index

            >>> self.at['a']

            Access element `'b'` using the second field index

            >>> self.iat[:, 'b']

            Access element with unique key combination ['c', 'd']

            >>> self.iat['c', 'd']

        """

        return _AtIndexer(self)

    @property
    def cols(self) -> _ColumnsWrapper:
        """
        Access a column as a Pandas Series

        Returns:
            Pandas Series of column

        Examples:
            Access column `a`:

            >>> self.cols.a

            Sum column `a`:

            >>> self.cols.a.sum()

        """

        return self._cols

    def __repr__(self) -> str:
        record_class_name = self.record_class.__name__
        header = f'DataClassFrame[{record_class_name}]\n'

        # Get df info
        df_repr = self.df.__repr__()
        return header + df_repr

    def head(self, n: int = 5) -> 'DataClassFrame[RecordT]':
        """
        Provide first `n` rows of self

        Args:
            n: First `n` rows to output

        Returns: DataClassFrame of head

        """

        new_dcf = self.copy(deep=False)
        new_dcf.df = self.df.head(n=n)
        return new_dcf

    def copy(self, deep: bool = True) -> 'DataClassFrame[RecordT]':
        """
        Copy self

        Args:
            deep: Perform deep copy or not

        Returns: copy of DataClassFrame

        """

        if deep:
            return deepcopy(self)
        else:
            return copy(self)

    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert to dataframe. Copy data to prevent side-effects.

        Returns: Pandas DataFrame of same data

        """

        return self.df.copy(deep=True)