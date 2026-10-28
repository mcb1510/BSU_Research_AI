from __future__ import annotations
"""Todo list tool — lets agents track tasks and progress."""

import json
from pathlib import Path
from .base import BaseTool


class TodoListTool(BaseTool):
    name = "todo_list"
    description = (
        "Create and manage a task list to track progress on multi-step work. "
        "Commands: create (start a new list), add (add tasks), complete (mark done), "
        "list (show current tasks), remove (delete a task)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["create", "add", "complete", "list", "remove"],
                "description": "The operation to perform on the task list.",
            },
            "task_list_description": {
                "type": "string",
                "description": "Description for 'create' command — summarizes what the list is for.",
            },
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_description": {"type": "string"},
                        "details": {"type": "string"},
                    },
                    "required": ["task_description"],
                },
                "description": "List of tasks for 'create' or 'add' commands.",
            },
            "completed_task_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs to mark complete. Used with 'complete' command.",
            },
            "remove_task_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs to remove. Used with 'remove' command.",
            },
            "context_update": {
                "type": "string",
                "description": "Optional context note to save with completed tasks.",
            },
        },
        "required": ["command"],
    }

    def __init__(self):
        self._lists: dict = {}  # session-scoped state
        self._current_list: str | None = None

    def execute(
        self,
        command: str,
        task_list_description: str | None = None,
        tasks: list | None = None,
        completed_task_ids: list | None = None,
        remove_task_ids: list | None = None,
        context_update: str | None = None,
    ) -> str:
        if command == "create":
            return self._create(task_list_description, tasks)
        elif command == "add":
            return self._add(tasks)
        elif command == "complete":
            return self._complete(completed_task_ids, context_update)
        elif command == "list":
            return self._list()
        elif command == "remove":
            return self._remove(remove_task_ids)
        else:
            return f"Unknown command: {command}"

    def _create(self, description: str | None, tasks: list | None) -> str:
        list_id = "default"
        self._lists[list_id] = {
            "description": description or "Task list",
            "tasks": [],
            "context": [],
            "_next_id": 1,
        }
        self._current_list = list_id

        if tasks:
            self._add_tasks_to(list_id, tasks)

        return self._render(list_id)

    def _add(self, tasks: list | None) -> str:
        if not self._current_list or self._current_list not in self._lists:
            return "No active task list. Use 'create' first."
        if not tasks:
            return "No tasks provided."
        self._add_tasks_to(self._current_list, tasks)
        return self._render(self._current_list)

    def _add_tasks_to(self, list_id: str, tasks: list):
        lst = self._lists[list_id]
        for t in tasks:
            task_id = str(lst["_next_id"])
            lst["_next_id"] += 1
            lst["tasks"].append({
                "id": task_id,
                "description": t.get("task_description", str(t)),
                "details": t.get("details", ""),
                "completed": False,
            })

    def _complete(self, ids: list | None, context: str | None) -> str:
        if not self._current_list or self._current_list not in self._lists:
            return "No active task list."
        if not ids:
            return "No task IDs provided."
        lst = self._lists[self._current_list]
        completed = []
        for task in lst["tasks"]:
            if task["id"] in ids:
                task["completed"] = True
                completed.append(task["id"])
        if context:
            lst["context"].append(context)
        return self._render(self._current_list)

    def _remove(self, ids: list | None) -> str:
        if not self._current_list or self._current_list not in self._lists:
            return "No active task list."
        if not ids:
            return "No task IDs provided."
        lst = self._lists[self._current_list]
        lst["tasks"] = [t for t in lst["tasks"] if t["id"] not in ids]
        return self._render(self._current_list)

    def _list(self) -> str:
        if not self._current_list or self._current_list not in self._lists:
            return "No active task list. Use 'create' first."
        return self._render(self._current_list)

    def _render(self, list_id: str) -> str:
        lst = self._lists[list_id]
        lines = [f"Task List: {lst['description']}"]
        lines.append(f"Progress: {sum(t['completed'] for t in lst['tasks'])}/{len(lst['tasks'])} done\n")
        for task in lst["tasks"]:
            status = "✓" if task["completed"] else "○"
            lines.append(f"  [{status}] #{task['id']}. {task['description']}")
            if task.get("details"):
                lines.append(f"       {task['details']}")
        return "\n".join(lines)
