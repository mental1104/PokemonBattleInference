package catalog

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"pokemonbattleinference/server/internal/postgres"
	"testing"
)

// TestInferenceProjectionPostgres 读取 runner 的独占已初始化 PG，覆盖所有合法资料而非只查 damaging 列表。
// t 管理断言/连接清理；可选 PBI_TEST_INFERENCE_SNAPSHOT_OUTPUT 仅输出本次测试资料供 Python 原投影差分。
func TestInferenceProjectionPostgres(t *testing.T) {
	dsn := os.Getenv("PBI_TEST_CATALOG_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_CATALOG_DSN is required for knowledge integration")
	}
	db, err := postgres.Open(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	store := New(db)
	result, err := store.Inference(context.Background(), "pokemon-champion", 25, []int{1, 25, 149, 212, 461, 474, 464})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Pokemon) != 7 || len(result.Items) != 6 || len(result.Chart) != 324 || result.Rules.Generation != 9 || result.Rules.VersionGroup != 25 {
		t.Fatalf("unexpected complete projection: pokemon=%d items=%d chart=%d rules=%+v", len(result.Pokemon), len(result.Items), len(result.Chart), result.Rules)
	}
	if !result.Pokemon[0].CanEvolve || result.Pokemon[2].CanEvolve || result.Pokemon[2].Base.Attack != 134 {
		t.Fatal("evolution or original base stats were changed")
	}
	statuses := map[string]bool{}
	for _, pokemon := range result.Pokemon {
		previous := 0
		for _, move := range pokemon.Moves {
			if move.ID <= previous || move.PP < 1 {
				t.Fatalf("invalid move ordering or PP: pokemon=%d move=%+v", pokemon.ID, move)
			}
			previous = move.ID
			statuses[move.Capability.Status] = true
		}
	}
	if !statuses["supported"] || !statuses["partial"] || !statuses["unsupported"] {
		t.Fatalf("legal unsupported candidates were lost: %+v", statuses)
	}
	for _, axis := range []struct {
		rules   string
		version int
		ids     []int
	}{{"missing", 25, []int{1}}, {"pokemon-champion", 24, []int{1}}, {"pokemon-champion", 25, []int{999999}}, {"pokemon-champion", 25, nil}} {
		_, err = store.Inference(context.Background(), axis.rules, axis.version, axis.ids)
		var input *CalculationInputError
		if !errors.As(err, &input) {
			t.Fatalf("invalid axis was not rejected: %+v err=%v", axis, err)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = store.Inference(ctx, "pokemon-champion", 25, []int{1}); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled query error=%v", err)
	}
	if output := os.Getenv("PBI_TEST_INFERENCE_SNAPSHOT_OUTPUT"); output != "" {
		// 仅测试入口写到 runner 指定的独占报告路径；生产 Store 不输出或缓存资料。
		body, marshalErr := json.MarshalIndent(result, "", "  ")
		if marshalErr != nil {
			t.Fatal(marshalErr)
		}
		if err = os.WriteFile(output, body, 0600); err != nil {
			t.Fatal(err)
		}
	}
}
