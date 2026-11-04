import { describe, expect, it } from "vitest";
import type { Table } from "../api";
import { parsePgUrl, suggestChanges } from "./connection";

describe("parsePgUrl", () => {
  it("parses every part of a connection URL", () => {
    expect(parsePgUrl("postgresql://bob:p%40ss@db.example.com:6543/shop?sslmode=require")).toEqual({
      host: "db.example.com", port: "6543", user: "bob", password: "p@ss", database: "shop", sslmode: "require",
    });
  });
  it("accepts the postgres:// scheme and omits missing parts", () => {
    expect(parsePgUrl("postgres://localhost/mydb")).toEqual({ host: "localhost", database: "mydb" });
  });
  it("rejects other schemes and garbage", () => {
    expect(parsePgUrl("mysql://a@b/c")).toBeNull();
    expect(parsePgUrl("not a url")).toBeNull();
  });
});

const col = (name: string, type: string, primary_key = false) => ({ name, type, nullable: true, primary_key });
const table = (name: string, columns: ReturnType<typeof col>[], kind: Table["kind"] = "table"): Table => ({ name, kind, columns });

describe("suggestChanges", () => {
  it("builds drop / delete / null-out suggestions from the first usable table", () => {
    const s = suggestChanges([table("orders", [col("order_id", "INTEGER", true), col("status", "TEXT"), col("amount", "NUMERIC")])]);
    expect(s.map((x) => x.sql)).toEqual([
      "ALTER TABLE orders DROP COLUMN status;",
      "DELETE FROM orders WHERE order_id % 4 = 0;",
      "UPDATE orders SET status = NULL;",
    ]);
  });
  it("ignores views and single-column tables", () => {
    expect(suggestChanges([table("v", [col("a", "TEXT"), col("b", "TEXT")], "view"), table("t", [col("a", "TEXT")])])).toEqual([]);
  });
});
