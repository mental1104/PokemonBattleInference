package nativeworker

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/jobs"
	"reflect"
	"testing"
)

// projectionJSON 为t读取value的完整JSON语义；Number避免测试把大整数转换为浮点后误判相等。
func projectionJSON(t *testing.T, value []byte) any {
	t.Helper()
	decoder := json.NewDecoder(bytes.NewReader(value))
	decoder.UseNumber()
	var result any
	if err := decoder.Decode(&result); err != nil {
		t.Fatal(err)
	}
	return result
}

// TestSharedProjectionPreservesFieldsAndActualSlotIdentity 对照完整正式fixture，证明选择的确进入请求且原状态/槽身份不变。
func TestSharedProjectionPreservesFieldsAndActualSlotIdentity(t *testing.T) {
	directory := os.Getenv("PBI_CONTRACT_FIXTURES")
	if directory == "" {
		directory = filepath.Join("..", "..", "..", "tests", "vectors")
	}
	encoded, err := os.ReadFile(filepath.Join(directory, "abi-calculations.v1.request.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Operations []json.RawMessage `json:"operations"`
	}
	if err := json.Unmarshal(encoded, &fixture); err != nil {
		t.Fatal(err)
	}
	var operation json.RawMessage
	for _, value := range fixture.Operations {
		var header struct {
			Kind string `json:"kind"`
		}
		if err := json.Unmarshal(value, &header); err != nil {
			t.Fatal(err)
		}
		if header.Kind == "fixed_battle" {
			operation = value
			break
		}
	}
	var state struct {
		State struct {
			Attacker struct {
				Spec struct {
					Moves []json.RawMessage `json:"moves"`
				} `json:"spec"`
				Slots []json.RawMessage `json:"move_slots"`
			} `json:"attacker"`
			Defender struct {
				Spec struct {
					Moves []json.RawMessage `json:"moves"`
				} `json:"spec"`
				Slots []json.RawMessage `json:"move_slots"`
			} `json:"defender"`
		} `json:"state"`
	}
	if err := json.Unmarshal(operation, &state); err != nil {
		t.Fatal(err)
	}
	if len(state.State.Attacker.Spec.Moves) != 1 || len(state.State.Defender.Spec.Moves) != 1 {
		t.Fatal("shared fixed fixture is missing")
	}
	attacker := jobs.FrozenMove{Spec: state.State.Attacker.Spec.Moves[0], Slot: state.State.Attacker.Slots[0]}
	defender := jobs.FrozenMove{Spec: state.State.Defender.Spec.Moves[0], Slot: state.State.Defender.Slots[0]}
	for _, move := range []*jobs.FrozenMove{&attacker, &defender} {
		var value struct {
			ID int `json:"move_id"`
		}
		if err := json.Unmarshal(move.Spec, &value); err != nil {
			t.Fatal(err)
		}
		move.MoveID = value.ID
	}
	request, err := json.Marshal(struct {
		Schema     int               `json:"schema_version"`
		Operations []json.RawMessage `json:"operations"`
	}{1, []json.RawMessage{operation}})
	if err != nil {
		t.Fatal(err)
	}
	template := jobs.FixedBattleTemplate{ContractVersion: "fixed-battle-move-pool.v1", Request: request,
		AttackerMoves: []jobs.FrozenMove{attacker}, DefenderMoves: []jobs.FrozenMove{defender}}
	projector, err := newRequestProjector(&template)
	if err != nil {
		t.Fatal(err)
	}
	item := jobs.CaseDefinition{AttackerMoves: []int{attacker.MoveID}, DefenderMoves: []int{defender.MoveID}}
	actual, err := projector.request(item)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(projectionJSON(t, actual), projectionJSON(t, request)) {
		t.Fatal("shared projection changed the original complete request")
	}
	// 未知选择会被拒绝；不能为缺失招式悄悄沿用代表配置。
	item.AttackerMoves = []int{700001}
	if _, err := projector.request(item); err == nil {
		t.Fatal("unknown selected move reused the representative")
	}
	// 投影结果拥有独立字节；调用结束后修改其缓冲区不能污染下一case或模板。
	actual[0] = 'x'
	item.AttackerMoves = []int{attacker.MoveID}
	repeated, err := projector.request(item)
	if err != nil || !reflect.DeepEqual(projectionJSON(t, repeated), projectionJSON(t, request)) {
		t.Fatalf("projection buffer aliases frozen input: %v", err)
	}
}
