from store import Student, StudentStore


def test_list_students_preserves_insertion_order():
    store = StudentStore()
    store.add(Student(id="s1", name="Ada"))
    store.add(Student(id="s2", name="Grace"))

    assert [student.id for student in store.list()] == ["s1", "s2"]
