package nativeworker_test

import (
	"bytes"
	"context"
	"encoding/json"
	"pokemonbattleinference/server/internal/corebridge"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/nativeworker"
	"testing"
)

// TestPublicFixedTemplateProjectionUsesActualCore 核对公开薄入口保持完整正式fixture的真实Core结果。
// t接收读取/原生调用失败；不需要PG，不用虚构成功响应替代实际计算。
func TestPublicFixedTemplateProjectionUsesActualCore(t *testing.T) {
	request := fixedRequest(t, "attacker", 100)
	var batch struct {
		Operations []struct {
			State struct {
				Attacker frozenFixtureSide `json:"attacker"`
				Defender frozenFixtureSide `json:"defender"`
			} `json:"state"`
		} `json:"operations"`
	}
	if err := json.Unmarshal(request, &batch); err != nil || len(batch.Operations) != 1 {
		t.Fatalf("invalid actual fixed fixture: %v", err)
	}
	attacker := frozenFixtureMove(t, batch.Operations[0].State.Attacker)
	defender := frozenFixtureMove(t, batch.Operations[0].State.Defender)
	template := &jobs.FixedBattleTemplate{ContractVersion: "fixed-battle-move-pool.v1", Request: request,
		AttackerMoves: []jobs.FrozenMove{attacker, alternateFrozenMove(t, attacker)}, DefenderMoves: []jobs.FrozenMove{defender}}
	item := jobs.CaseDefinition{AttackerMoves: []int{attacker.MoveID}, DefenderMoves: []int{defender.MoveID}}
	projected, err := nativeworker.ProjectFixedBattleTemplate(template, item)
	if err != nil {
		t.Fatal(err)
	}
	want, err := corebridge.Compute(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	actual, err := corebridge.Compute(context.Background(), projected)
	if err != nil || !bytes.Equal(actual, want) {
		t.Fatalf("public projection changed the actual complete Core response: %v", err)
	}
	if _, err := nativeworker.ProjectFixedBattleTemplate(nil, item); err == nil {
		t.Fatal("nil template was accepted")
	}
	for _, ids := range [][]int{nil, {attacker.MoveID, attacker.MoveID}, {700001, attacker.MoveID}, {999999}, {0}, {1, 2, 3, 4, 5}} {
		invalid := item
		invalid.AttackerMoves = ids
		if _, err := nativeworker.ProjectFixedBattleTemplate(template, invalid); err == nil {
			t.Fatalf("invalid fixed move selection was accepted: %v", ids)
		}
	}
}
