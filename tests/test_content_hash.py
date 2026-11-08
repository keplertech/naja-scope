# SPDX-License-Identifier: Apache-2.0
"""Content comparison through the raw engine, including snapshot persistence."""

import asyncio
import re

import pytest
from najaeda import naja

from naja_scope import api, server
from naja_scope.errors import NoDesignError, ScopeError


def test_content_hash_snapshot_round_trip(uart_session, tmp_path):
    before = api.get_content_hash()
    assert before["module"] == "uart_top"
    assert re.fullmatch(r"[0-9a-f]{64}", before["content_hash"])
    assert before["algorithm"] == "sha256"
    assert before["format_version"] == naja.getContentHashVersion()
    assert before["naja_git_hash"] == naja.getGitHash()
    assert api.get_content_hash("uart_top") == before
    child = api.get_content_hash("uart_tx")
    assert child["content_hash"] != before["content_hash"]
    api.save_snapshot(str(tmp_path / "snapshot"))
    api.SESSION.reset()
    api.load_snapshot(str(tmp_path / "snapshot"))
    assert api.get_content_hash() == before
    assert api.get_content_hash("uart_tx") == child


def test_content_hash_tracks_descendant_wiring(uart_session):
    before = api.get_content_hash()
    child = api.get_content_hash("uart_tx")
    model = next(i.getModel() for i in api.SESSION.require_top().design.getInstances()
                 if i.getModel().getName() == "uart_tx")
    # Disconnect a port inside the child model without changing its parent.
    port = model.getTerm("tx_o")
    net = port.getNet()
    assert net is not None
    port.setNet(None)
    assert api.get_content_hash("uart_tx") != child
    assert api.get_content_hash() != before
    port.setNet(net)
    assert api.get_content_hash() == before


def test_content_hash_errors(uart_session):
    with pytest.raises(ScopeError) as exc:
        api.get_content_hash("uart_txx")
    assert "uart_tx" in exc.value.suggestions
    api.SESSION.reset()
    with pytest.raises(NoDesignError):
        api.get_content_hash()


def test_content_hash_mcp(uart_session):
    tool = next(t for t in asyncio.run(server.mcp.list_tools())
                if t.name == "get_content_hash")
    assert tool.annotations.readOnlyHint
    assert server.get_content_hash() == api.get_content_hash()
