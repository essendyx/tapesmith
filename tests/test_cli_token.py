"""Tests für `p12 token add|list|revoke` (über `tapesmith.cli.main`)."""

import json

from tapesmith import cli, netinfo


def test_token_add_list_revoke(app_home, capsys):
    assert cli.main(["token", "add", "Handy", "--rolle", "familie"]) == 0
    out = capsys.readouterr().out
    assert "nur jetzt angezeigt" in out
    assert "p12_" in out

    assert cli.main(["token", "list"]) == 0
    out = capsys.readouterr().out
    assert "Handy" in out
    assert "Familie" in out
    assert "p12_" not in out

    assert cli.main(["token", "add", "Handy", "--rolle", "familie"]) == 1
    capsys.readouterr()

    assert cli.main(["token", "revoke", "Handy"]) == 0
    out = capsys.readouterr().out
    assert "widerrufen" in out

    assert cli.main(["token", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == []


def test_token_add_familie_mit_lan(app_home, capsys, monkeypatch):
    cli.main(["config", "set", "lan.enabled", "true"])
    cli.main(["config", "set", "lan.allowed_networks", "[\"192.0.2.0/24\"]"])
    capsys.readouterr()
    monkeypatch.setattr(netinfo, "local_ipv4_addresses", lambda *a, **kw: ["192.0.2.50"])

    assert cli.main(["token", "add", "Handy", "--rolle", "familie"]) == 0
    out = capsys.readouterr().out
    assert "http://192.0.2.50:8712/familie#t=p12_" in out


def test_token_add_familie_ohne_lan_zeigt_hinweis_statt_link(app_home, capsys, monkeypatch):
    """lan.enabled ist aus (Standard): auch wenn eine lokale Adresse zufaellig in
    lan.allowed_networks liegt, darf kein Familienlink erscheinen, nur der Hinweis."""
    monkeypatch.setattr(netinfo, "local_ipv4_addresses", lambda *a, **kw: ["192.0.2.50"])

    assert cli.main(["token", "add", "Handy", "--rolle", "familie"]) == 0
    out = capsys.readouterr().out
    assert "http://" not in out
    assert "LAN ist aus" in out
    assert "lan.enabled" in out


def test_token_add_familie_ohne_lan_json_hat_leere_family_urls(app_home, capsys, monkeypatch):
    monkeypatch.setattr(netinfo, "local_ipv4_addresses", lambda *a, **kw: ["192.0.2.50"])

    assert cli.main(["token", "add", "Handy2", "--rolle", "familie", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["family_urls"] == []


def test_token_add_json(app_home, capsys):
    assert cli.main(["token", "add", "Drucker", "--rolle", "drucken", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["token"]["name"] == "Drucker"
    assert data["token"]["role"] == "drucken"
    assert data["secret"].startswith("p12_")
    assert data["family_urls"] == []


def test_token_revoke_unbekannt(app_home, capsys):
    assert cli.main(["token", "revoke", "Nichtvorhanden"]) == 1
    err = capsys.readouterr().err
    assert "Fehler" in err
