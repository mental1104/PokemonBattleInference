package catalog

import (
	"context"
	"os"
	"pokemonbattleinference/server/internal/postgres"
	"testing"
)

// TestLegacyFullPokedexSnapshotPostgres 验证旧样例的非Champion全raw物种/形态仍可读取，类型知识保持完整。
func TestLegacyFullPokedexSnapshotPostgres(t *testing.T) {
	dsn := os.Getenv("PBI_TEST_CATALOG_DSN")
	if dsn == "" {
		t.Skip("PBI_TEST_CATALOG_DSN is required")
	}
	ctx := context.Background()
	db, err := postgres.Open(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	snapshot, err := New(db).LegacyDamage(ctx, 10021, 598)
	if err != nil {
		t.Fatal(err)
	}
	if snapshot.Attacker.Base != [6]int64{89, 145, 90, 105, 80, 91} || snapshot.Defender.Base != [6]int64{74, 94, 131, 54, 116, 20} {
		t.Fatalf("raw historical example changed: %+v", snapshot)
	}
	if len(snapshot.Chart) != 324 || len(snapshot.TypeNames) != 18 || snapshot.TypeNames["NORMAL"] != 1 || snapshot.TypeNames["FAIRY"] != 18 {
		t.Fatal("legacy knowledge is incomplete")
	}
	if _, err = New(db).LegacyDamage(ctx, 0, 598); err == nil {
		t.Fatal("missing raw Pokemon was accepted")
	}
}
