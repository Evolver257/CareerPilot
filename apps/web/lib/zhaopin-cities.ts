export const ZHAOPIN_CITY_CODES: Record<string, string> = {
  全国: "489",
  北京: "530",
  天津: "531",
  上海: "538",
  重庆: "551",
  石家庄: "565",
  太原: "576",
  呼和浩特: "587",
  沈阳: "599",
  大连: "600",
  长春: "613",
  哈尔滨: "622",
  南京: "635",
  无锡: "636",
  苏州: "639",
  杭州: "653",
  宁波: "654",
  合肥: "664",
  福州: "681",
  厦门: "682",
  南昌: "691",
  济南: "702",
  青岛: "703",
  郑州: "719",
  武汉: "736",
  长沙: "749",
  广州: "763",
  深圳: "765",
  珠海: "766",
  佛山: "768",
  东莞: "779",
  南宁: "785",
  海口: "799",
  成都: "801",
  贵阳: "822",
  昆明: "831",
  拉萨: "847",
  西安: "854",
  兰州: "864",
  银川: "886",
  乌鲁木齐: "890",
};

export const ZHAOPIN_CITY_OPTIONS = Object.entries(ZHAOPIN_CITY_CODES).map(([name, code]) => ({ name, code }));

export function resolveZhaopinCityCode(value: string): string | null {
  const normalized = value.trim().replace(/[市]$/, "");
  if (!normalized) return null;
  if (/^\d{2,6}$/.test(normalized)) return normalized;
  return ZHAOPIN_CITY_CODES[normalized] || null;
}

export function zhaopinCityName(code: string | null | undefined): string {
  if (!code) return "";
  return ZHAOPIN_CITY_OPTIONS.find((item) => item.code === code)?.name || code;
}
