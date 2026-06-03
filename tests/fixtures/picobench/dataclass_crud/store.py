from dataclasses import dataclass


@dataclass
class Student:
    id: str
    name: str


class StudentStore:
    def __init__(self):
        self._items = {}

    def add(self, student):
        self._items[student.id] = student

    def get(self, student_id):
        return self._items.get(student_id)
