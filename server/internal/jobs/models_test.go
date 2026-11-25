package jobs_test

import (
	"pokemonbattleinference/server/internal/jobs"
	"testing"
)

// TestLegacyFingerprintAndExactNormalization 对照原 Python 指纹字段格式的独立冻结 SHA-256。
func TestLegacyFingerprintAndExactNormalization(t *testing.T) {
	result := jobs.Result{Status: jobs.Succeeded, AttackerWin: &jobs.Fraction{"2", "6"}, DefenderWin: &jobs.Fraction{"4", "6"}, Draw: &jobs.Fraction{"0", "5"}, ExpectedTurns: &jobs.ExpectedTurns{Kind: "finite", Value: &jobs.Fraction{"6", "4"}}, Nodes: 23, Edges: 41, Budget: 64}
	normalized, err := result.Normalize()
	if err != nil {
		t.Fatal(err)
	}
	if normalized.AttackerWin.Numerator != "1" || normalized.AttackerWin.Denominator != "3" || normalized.ExpectedTurns.Value.Numerator != "3" || normalized.ExpectedTurns.Value.Denominator != "2" {
		t.Fatalf("exact normalization differs: %+v", normalized)
	}
	if got := normalized.Fingerprint(); got != "3d933f823603b08ae6ecc41807db38674b85e923d6085e65d44920fbaf300b74" {
		t.Fatalf("legacy fingerprint differs: %s", got)
	}
	// Normalize 返回新分数对象，不能改变调用者原快照。
	if result.AttackerWin.Numerator != "2" || result.ExpectedTurns.Value.Numerator != "6" {
		t.Fatal("normalization mutated input")
	}
	invalid := result
	invalid.Draw = &jobs.Fraction{"1", "2"}
	if _, err = invalid.Normalize(); err == nil {
		t.Fatal("non-conserving probability was accepted")
	}
	invalid = result
	invalid.ExpectedTurns = &jobs.ExpectedTurns{Kind: "infinite", Value: &jobs.Fraction{"1", "1"}}
	if _, err = invalid.Normalize(); err == nil {
		t.Fatal("infinite turns with fraction were accepted")
	}
}
