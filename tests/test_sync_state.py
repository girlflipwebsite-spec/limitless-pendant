from pendant.sync_state import PageKey, SyncState


def test_new_pages_are_new_until_marked_seen(tmp_path):
    state = SyncState(path=tmp_path / "sync_state.json")
    key = PageKey(session=1, run=2, seq=3)

    assert state.is_new(key)
    state.mark_seen(key)
    assert not state.is_new(key)


def test_state_persists_across_instances(tmp_path):
    path = tmp_path / "sync_state.json"
    key = PageKey(session=5, run=0, seq=10)

    state = SyncState(path=path)
    state.mark_seen(key)
    state.last_sync_iso = "2026-01-01T00:00:00"
    state.save()

    reloaded = SyncState(path=path)
    assert not reloaded.is_new(key)
    assert reloaded.last_sync_iso == "2026-01-01T00:00:00"
