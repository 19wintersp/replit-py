"""Interface with the Replit Database."""
import asyncio
import json
import os
from sys import stderr
from typing import Any, Callable, Dict, List, Tuple, Union

import aiohttp

from . import _async

asyncio.run = _async.run


JSON_TYPE = Union[str, int, float, bool, type(None), dict, list]


class JSONKey:
    """Represents a key in the database that holds a JSON value.

    db.jsonkey() will initialize an instance for you,
    you don't have to do it manually.
    """

    __slots__ = ("db", "key", "dtype", "get_default", "discard_bad_data")

    def __init__(
        self,
        db: Any,
        key: str,
        dtype: JSON_TYPE,
        get_default: Callable = None,
        discard_bad_data: bool = False,
    ) -> None:
        """Initialize the key.

        Args:
            db (Any): An instance of ReplitDb
            key (str): The key to read
            dtype (JSON_TYPE): The datatype the key should be, can be typing.Any.
            get_default (Callable): A function that returns the default
                value if the key is not set. If it is None (the default) the dtype
                argument is used.
            discard_bad_data (bool): Don't prompt if bad data is read, overwrite it
                with the default. Defaults to False.
        """
        self.db = db
        self.key = key
        self.dtype = dtype
        self.get_default = get_default
        self.discard_bad_data = discard_bad_data

    def _default(self) -> JSON_TYPE:
        get_default_func = self.get_default or self.dtype
        return get_default_func()

    def _is_valid_type(self, data: JSON_TYPE) -> bool:
        return self.dtype is Any or isinstance(data, self.dtype)

    def _type_mismatch_msg(self, data: Any) -> str:
        return (
            f"Type mismatch: Got type {type(data).__name__},"
            "expected {self.dtype.__name__}"
        )

    def get(self) -> JSON_TYPE:
        """Get the value of the key.

        If an invalid JSON value is read or the type does not match, it will show a
            prompt asking the user what to do unless discard_bad_data is set.

        Returns:
            JSON_TYPE: The value read from the database
        """
        try:
            read = self.db[self.key]
        except KeyError:
            print(f"Database key {self.key} not set, setting it to default value")
            default = self._default()
            self.db[self.key] = default
            return default

        try:
            data = json.loads(read)
        except json.JSONDecodeError:
            return self._error("Invalid JSON data read", read)

        if not self._is_valid_type(data):
            return self._error(self._type_mismatch_msg(data), read,)
        return data

    def _error(self, error: str, read: str) -> JSON_TYPE:
        print(f"Error reading key {self.key!r}: {error}", file=stderr)
        if self.discard_bad_data:
            val = self._default()
            self.db[self.key] = json.dumps(val)
            print(f"Wrote default to key {self.key!r}")
            return val
        return self._should_discard_prompt(error, read)

    def _should_discard_prompt(self, error: str, read: str) -> bool:
        while True:
            choice = input(
                "d to use default, v to view the invalid data, c to insert custom "
                "value, ^C to exit: "
            )
            if choice.startswith("d"):
                print("Writing default...")
                val = self._default()
                self.db[self.key] = val
                return val
            elif choice.startswith("v"):
                print(f"Data read from key: {read!r}")
            elif choice.startswith("c"):
                toset = input(
                    f"Enter data to write, should be of type {self.dtype.__name__!r}"
                    " (leave blank to return to menu): "
                )
                if not toset:
                    continue
                try:
                    data = json.loads(toset)
                except json.JSONDecodeError:
                    print("Invalid JSON data!")
                else:
                    if not self._is_valid_type(data):
                        print(self._type_mismatch_msg(data))
                        continue

                    self.db[self.key] = toset
                    print("Wrote data to key")
                    return data

    def set(self, data: JSON_TYPE) -> None:
        """Set the value of the jsonkey.

        Args:
            data (JSON_TYPE): The value to set it to.

        Raises:
            TypeError: The type of the value set does not match the datatype.
        """
        if not self._is_valid_type(data):
            raise TypeError(self._type_mismatch_msg(data))
        self.db[self.key] = json.dumps(data)


class ReplitDb(dict):
    """Interface with the Replit Database."""

    __slots__ = ("db_url", "sess")

    def __init__(self, db_url: str) -> None:
        """Initialize database. You shouldn't have to do this manually.

        Args:
            db_url (str): Database url to use.
        """
        self.db_url = db_url
        self.sess = _AsyncBackend(db_url)

    def __getitem__(self, key: str) -> str:
        """Get the value of an item from the database.

        Args:
            key (str): The key to retreive

        Raises:
            KeyError: Key is not set

        Returns:
            str: The value of the key
        """
        r = asyncio.run(self.sess.view(key))
        return r

    def __setitem__(self, key: str, value: str) -> None:
        """Set a key in the database to value.

        Args:
            key (str): The key to set
            value (str): The value to set it to
        """
        asyncio.run(self.sess.set(key, value))

    def __delitem__(self, key: str) -> None:
        """Delete a key from the database.

        Args:
            key (str): The key to delete
        """
        asyncio.run(self.sess.delete(key))

    def keys(self, prefix: str = "") -> Tuple[str]:
        """Return all of the keys in the database.

        Args:
            prefix (str): The prefix the keys must start with,
                blank means anything. Defaults to "".

        Returns:
            Tuple[str]: The keys found.
        """
        return asyncio.run(self.sess.list(prefix))

    def to_dict(self, prefix: str = "") -> Dict[str, str]:
        """Dump all data in the database into a dictionary.

        Args:
            prefix (str): The prefix the keys must start with,
                blank means anything. Defaults to "".

        Returns:
            Dict[str, str]: All keys in the database.
        """
        keys = self.keys()
        data = {}
        for k in keys:
            data[k] = self[k]
        return data

    def values(self) -> Tuple[str]:
        """Get every value in the database.

        Returns:
            Tuple[str]: The values in the database.
        """
        data = self.to_dict()
        return tuple(data.values())

    def items(self) -> Tuple[Tuple[str]]:
        return self.to_dict().items()

    def jsonkey(
        self,
        key: str,
        dtype: JSON_TYPE,
        get_default: Callable = None,
        discard_bad_data: bool = False,
    ) -> JSONKey:
        """Initialize a JSONKey instance.

        A JSONKey is used to easily read and set JSON data from the database.
        Arguments are the same as JSONKey constructor.

        Args:
            key (str): The key to read
            dtype (JSON_TYPE): The datatype the key should be, can be typing.Any.
            get_default (Callable): A function that returns the default
                value if the key is not set. If it is None (the default) the dtype
                argument is used.
            discard_bad_data (bool): Don't prompt if bad data is read, overwrite it
                with the default. Defaults to False.

        Returns:
            JSONKey: The initialized JSONKey instance.
        """
        return JSONKey(
            db=self,
            key=key,
            dtype=dtype,
            get_default=get_default,
            discard_bad_data=discard_bad_data,
        )

    def __repr__(self) -> str:
        """A representation of the database.

        Returns:
            A string representation of the database object.
        """
        return f"<ReplitDb(db_url={self.db_url!r})>"


class AsyncClient:
    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self.backend = _AsyncBackend(db_url)

    async def view(self, key: str) -> str:
        return await self.backend.view(key)

    async def list(self, prefix: str) -> List[str]:
        return await self.backend.list(prefix)

    async def delete(self, key: str) -> None:
        return await self.backend.delete(key)

    async def set(self, key: str, val: str) -> None:
        return await self.backend.set(key, val)

    async def to_dict(self) -> Dict[str, str]:
        ret = {}
        keys = await self.keys()
        for i in keys:
            ret[i] = await self.view(i)
        return ret

    async def keys(self) -> Tuple[str]:
        return tuple(await self.list(""))

    async def values(self) -> Tuple[str]:
        return tuple((await self.to_dict()).values())


class _AsyncBackend:
    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    async def set(self, key: str, val: str) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.post(self.db_url, data={key: val}) as response:
                response.raise_for_status()

    async def view(self, key: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.db_url + "/" + key) as response:
                if response.status == 404:
                    raise KeyError(key)
                response.raise_for_status()
                return await response.text()

    async def delete(self, key: str) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.delete(self.db_url + "/" + key) as response:
                response.raise_for_status()

    async def list(self, prefix: str) -> Tuple[str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.db_url + "?prefix=" + prefix) as response:
                response.raise_for_status()
                if not await response.text():
                    return tuple()
                else:
                    return tuple((await response.text()).split("\n"))


db_url = os.environ.get("REPLIT_DB_URL")
if db_url:
    db = ReplitDb(db_url)
else:
    print(
        "Warning: REPLIT_DB_URL does not exist, are we running on repl.it? "
        "Database will not function.",
        file=stderr,
    )
    db = None
