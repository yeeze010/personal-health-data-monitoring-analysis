import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const dir = path.dirname(fileURLToPath(import.meta.url));
const xlsxPath = path.join(dir, "个人健康生活网络数据监测与分析系统_开发排期任务分工测试用例.xlsx");
const input = await FileBlob.load(xlsxPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const checks = [
  ["项目总览", "A1:B7", "项目名称"],
  ["开发里程碑", "A1:E7", "P0"],
  ["任务分工", "A1:H14", "FE-01"],
  ["测试用例", "A1:G16", "TC-001"],
  ["验收清单", "A1:D10", "业务闭环"],
  ["风险台账", "A1:F7", "隐私"],
];

await fs.mkdir(path.join(dir, "xlsx-render"), { recursive: true });
for (const [sheetName, range, keyword] of checks) {
  const table = await workbook.inspect({
    kind: "table",
    range: `${sheetName}!${range}`,
    include: "values,formulas",
    tableMaxRows: 20,
    tableMaxCols: 10,
  });
  if (!table.ndjson || !table.ndjson.includes(keyword)) {
    console.error(`检查失败：${sheetName}`);
    process.exit(1);
  }
  const png = await workbook.render({ sheetName, range, format: "png", scale: 1 });
  await fs.writeFile(path.join(dir, "xlsx-render", `${sheetName}.png`), Buffer.from(await png.arrayBuffer()));
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
if (errors.ndjson && errors.ndjson.includes("#")) {
  console.error(errors.ndjson);
  process.exit(1);
}

console.log("workbook verified");
