from store import Student, StudentStore


def test_student_store_crud():
    store = StudentStore()
    store.add(Student(id="s1", name="Ada"))

    assert store.get("s1").name == "Ada"
    assert store.update("s1", name="Grace") is True
    assert store.get("s1").name == "Grace"
    assert store.delete("s1") is True
    assert store.get("s1") is None


def test_missing_student_update_and_delete_return_false():
    store = StudentStore()

    assert store.update("missing", name="Nobody") is False
    assert store.delete("missing") is False
