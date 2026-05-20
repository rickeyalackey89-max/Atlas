from mlb.runtime.paths import mlb_paths


def test_mlb_paths_stay_inside_data_mlb():
    paths = mlb_paths()
    assert paths.data_root.name == "mlb"
    assert paths.raw.parent == paths.data_root
    assert paths.models.parent == paths.data_root
