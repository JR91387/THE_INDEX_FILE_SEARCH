# SPDX-License-Identifier: MIT
"""The MCP tools: JSON Schemas built from the query_describe data, and calls into the shared query layer."""
import json

from . import db, query
from .query_describe import COMMANDS, NOTE

# MCP tool name -> query function name (`changes` is the document-event query).
ALIAS = {"changes": "changes_files"}
TYPES = {"integer": {"type": "integer"}, "string": {"type": "string"}, "boolean": {"type": "boolean"},
         "array of string": {"type": "array", "items": {"type": "string"}}}
CHECKS = {"integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "string": lambda v: isinstance(v, str),
          "boolean": lambda v: isinstance(v, bool), "array": lambda v: isinstance(v, list)}
NO_DB = "no database yet: run `the-index scan`"
INSTRUCTIONS = ("THE INDEX is a catalog of what exists on a machine or fleet. Use find to locate folders and "
                "documents by words, tree for where the space is, projects for folders holding AI-agent files, "
                "folder for one folder's contents, changes for recent document events, and describe for the "
                f"fields and limits. All tools are read-only. Note: {NOTE}.")


def _property(param):
    prop = dict(TYPES[param["type"]])
    for key, target in (("default", "default"), ("min", "minimum"), ("max", "maximum"), ("values", "enum")):
        if key in param:
            prop[target] = param[key]
    if param.get("note"):
        prop["description"] = param["note"]
    return prop


def _tool(spec):
    params = spec["params"]
    schema = {"type": "object", "properties": {p["name"]: _property(p) for p in params},
              "required": [p["name"] for p in params if p.get("required")], "additionalProperties": False}
    name = next((k for k, v in ALIAS.items() if v == spec["name"]), spec["name"])
    fields = ", ".join(spec["result_fields"])
    return {"name": name, "description": f"{spec['summary']}. Result fields: {fields}.", "inputSchema": schema}


def tools():
    return [_tool(spec) for spec in COMMANDS]


def _check(tool, args):
    """An error message when args do not fit the tool's schema, else None."""
    schema = tool["inputSchema"]
    if not isinstance(args, dict):
        return "arguments must be an object"
    for name in schema["required"]:
        if name not in args:
            return f"missing required argument: {name}"
    for name, value in args.items():
        if name not in schema["properties"]:
            return f"unknown argument: {name}"
        want = schema["properties"][name]["type"]
        if want == "array" and isinstance(value, str):
            args[name] = value = value.split()     # agents often send "two words" for a word list
        if not CHECKS[want](value):
            return f"argument {name} must be of type {want}"
    return None


def _result(envelope):
    return {"content": [{"type": "text", "text": json.dumps(envelope, ensure_ascii=False)}],
            "structuredContent": envelope, "isError": bool(envelope.get("error"))}


def error_result(message):
    return {"content": [{"type": "text", "text": message}], "isError": True}


class Session:
    """Holds the lazily opened read-only database for one server run."""

    def __init__(self, cfg):
        self.cfg, self.conn = cfg, None

    def call(self, name, args):
        known = {t["name"]: t for t in tools()}
        if name not in known:
            return error_result(f"unknown tool: {name}")
        args = {} if args is None else args
        problem = _check(known[name], args)
        if problem:
            return error_result(problem)
        if self.conn is None:
            if not self.cfg.db_path.exists():
                return error_result(NO_DB)
            self.conn = db.open(self.cfg.db_path)
        return _result(query.COMMANDS[ALIAS.get(name, name)](self.conn, args))
