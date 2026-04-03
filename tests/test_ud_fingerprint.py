from app.protocol.parsers.registry import _parse_ud_family


def test_ud_doc_example_cells_and_neighbors():
    payload = b"UD,220414,134652,A,22.571707,N,113.861396,E,0.1,0.0,100,7,60,90,1000,50,0000,4,1,460,0,9360,4082,131,9360,4092,148,9360,4091,143,9360,4153,141"
    d = _parse_ud_family(payload, "UD")
    assert d["gps_valid"] is True
    assert d["lat"] == 22.571707
    assert d["lng"] == 113.861396
    fp = d["lbs_wifi"]
    assert len(fp["cells"]) == 4
    assert fp["cells"][0]["mcc"] == "460"
    assert fp["cells"][0]["lac"] == "9360"
    assert fp["wifi"] == []


def test_ud_v_zero_gps_with_wifi():
    payload = b"UD,030426,125025,V,00.000000,N,000.000000,E,0,0,0,0,73,56,21218,0,00000000,1,255,460,0,21352,92126262,39,2,WIFI00,b8:80:35:96:2e:93,-52,WIFI01,ba:80:35:c6:2e:93,-52"
    d = _parse_ud_family(payload, "UD")
    assert d["gps_valid"] is False
    fp = d["lbs_wifi"]
    assert len(fp["cells"]) >= 1
    assert len(fp["wifi"]) >= 2
