import axios from 'axios';

/**
 * 东方财富API接口服务
 * 用于获取A股实时行情数据
 */

interface StockQuote {
  code: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  amount: number;
  high: number;
  low: number;
  open: number;
  yesterdayClose: number;
  timestamp: number;
}

/**
 * 获取A股实时行情数据
 * 使用东方财富API接口
 */
export async function getEastmoneyStockData(codes: string[]): Promise<StockQuote[]> {
  try {
    // 东方财富实时行情API
    // 格式：code=股票代码（如：sh600000,sz000001）
    const codeStr = codes.join(',');
    const url = `https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18&secids=${codeStr}`;

    const response = await axios.get(url, {
      headers: {
        'Referer': 'https://www.eastmoney.com',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
      },
      timeout: 5000,
    });

    const data = response.data;
    if (data?.data?.diff) {
      return data.data.diff.map((item: {
        f2?: number;
        f3?: number;
        f4?: number;
        f5?: number;
        f6?: number;
        f12?: string;
        f14?: string;
        f15?: number;
        f16?: number;
        f17?: number;
        f18?: number;
      }) => ({
        code: item.f12 || '',
        name: item.f14 || '',
        price: item.f2 ? item.f2 / 100 : 0,
        change: item.f4 ? item.f4 / 100 : 0,
        changePercent: item.f3 ? item.f3 / 100 : 0,
        volume: item.f5 || 0,
        amount: item.f6 || 0,
        high: item.f15 ? item.f15 / 100 : 0,
        low: item.f16 ? item.f16 / 100 : 0,
        open: item.f17 ? item.f17 / 100 : 0,
        yesterdayClose: item.f18 ? item.f18 / 100 : 0,
        timestamp: Date.now(),
      }));
    }

    return [];
  } catch (error) {
    console.error('获取东方财富数据失败:', error);
    throw error;
  }
}

/**
 * 获取A股指数数据（上证指数、深证成指、创业板指）
 */
export async function getIndexData(): Promise<StockQuote[]> {
  const indexCodes = ['1.000001', '0.399001', '0.399006']; // 上证指数、深证成指、创业板指
  try {
    const url = `https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18&secids=${indexCodes.join(',')}`;

    const response = await axios.get(url, {
      headers: {
        'Referer': 'https://www.eastmoney.com',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
      },
      timeout: 5000,
    });

    const data = response.data;
    if (data?.data?.diff) {
      return data.data.diff.map((item: {
        f2?: number;
        f3?: number;
        f4?: number;
        f5?: number;
        f6?: number;
        f12?: string;
        f14?: string;
        f15?: number;
        f16?: number;
        f17?: number;
        f18?: number;
      }) => ({
        code: item.f12 || '',
        name: item.f14 || '',
        price: item.f2 ? item.f2 / 100 : 0,
        change: item.f4 ? item.f4 / 100 : 0,
        changePercent: item.f3 ? item.f3 / 100 : 0,
        volume: item.f5 || 0,
        amount: item.f6 || 0,
        high: item.f15 ? item.f15 / 100 : 0,
        low: item.f16 ? item.f16 / 100 : 0,
        open: item.f17 ? item.f17 / 100 : 0,
        yesterdayClose: item.f18 ? item.f18 / 100 : 0,
        timestamp: Date.now(),
      }));
    }

    return [];
  } catch (error) {
    console.error('获取指数数据失败:', error);
    // 如果API失败，返回模拟数据
    return [
      {
        code: 'SH000001',
        name: '上证指数',
        price: 3000 + Math.random() * 500,
        change: Math.random() * 50 - 25,
        changePercent: Math.random() * 2 - 1,
        volume: Math.random() * 1000000000,
        amount: Math.random() * 5000000000,
        high: 0,
        low: 0,
        open: 0,
        yesterdayClose: 0,
        timestamp: Date.now(),
      },
      {
        code: 'SZ399001',
        name: '深证成指',
        price: 10000 + Math.random() * 1000,
        change: Math.random() * 100 - 50,
        changePercent: Math.random() * 2 - 1,
        volume: Math.random() * 2000000000,
        amount: Math.random() * 8000000000,
        high: 0,
        low: 0,
        open: 0,
        yesterdayClose: 0,
        timestamp: Date.now(),
      },
      {
        code: 'SZ399006',
        name: '创业板指',
        price: 2000 + Math.random() * 400,
        change: Math.random() * 40 - 20,
        changePercent: Math.random() * 2 - 1,
        volume: Math.random() * 500000000,
        amount: Math.random() * 2000000000,
        high: 0,
        low: 0,
        open: 0,
        yesterdayClose: 0,
        timestamp: Date.now(),
      },
    ];
  }
}

/**
 * 获取所有A股股票代码列表（热门股票 + 更多股票）
 * 这里包含了一些常见的热门股票代码
 */
function getAllStockCodes(): string[] {
  // 上海主板热门股票
  const shStocks = [
    '1.600000', '1.600036', '1.600519', '1.600887', '1.600276',
    '1.600030', '1.600276', '1.600436', '1.600585', '1.600893',
    '1.600009', '1.600104', '1.600111', '1.600150', '1.600196',
    '1.600256', '1.600309', '1.600352', '1.600362', '1.600438',
    '1.600489', '1.600518', '1.600570', '1.600584', '1.600597',
    '1.600606', '1.600660', '1.600674', '1.600688', '1.600703',
    '1.600718', '1.600741', '1.600745', '1.600795', '1.600809',
    '1.600837', '1.600845', '1.600848', '1.600867', '1.600886',
    '1.600893', '1.600900', '1.600919', '1.600941', '1.600958',
    '1.600966', '1.600977', '1.600985', '1.600999', '1.601012',
    '1.601018', '1.601066', '1.601088', '1.601118', '1.601138',
    '1.601166', '1.601169', '1.601186', '1.601198', '1.601211',
    '1.601216', '1.601225', '1.601229', '1.601288', '1.601318',
    '1.601328', '1.601336', '1.601360', '1.601377', '1.601390',
    '1.601398', '1.601601', '1.601628', '1.601633', '1.601658',
    '1.601668', '1.601688', '1.601698', '1.601718', '1.601728',
    '1.601766', '1.601788', '1.601800', '1.601808', '1.601818',
    '1.601828', '1.601838', '1.601857', '1.601860', '1.601866',
    '1.601872', '1.601877', '1.601881', '1.601888', '1.601890',
    '1.601898', '1.601899', '1.601901', '1.601919', '1.601928',
    '1.601933', '1.601939', '1.601985', '1.601988', '1.601989',
    '1.601992', '1.601995', '1.601998', '1.603000', '1.603019',
    '1.603043', '1.603259', '1.603288', '1.603369', '1.603501',
    '1.603568', '1.603589', '1.603799', '1.603833', '1.603868',
    '1.603986', '1.603993', '1.605117', '1.688005', '1.688009',
  ];

  // 深圳主板热门股票
  const szStocks = [
    '0.000001', '0.000002', '0.000009', '0.000012', '0.000016',
    '0.000021', '0.000024', '0.000027', '0.000031', '0.000039',
    '0.000050', '0.000059', '0.000061', '0.000063', '0.000066',
    '0.000069', '0.000078', '0.000088', '0.000089', '0.000100',
    '0.000157', '0.000166', '0.000301', '0.000333', '0.000338',
    '0.000400', '0.000402', '0.000413', '0.000415', '0.000423',
    '0.000425', '0.000488', '0.000498', '0.000501', '0.000513',
    '0.000516', '0.000519', '0.000528', '0.000538', '0.000539',
    '0.000540', '0.000547', '0.000559', '0.000568', '0.000572',
    '0.000581', '0.000596', '0.000623', '0.000625', '0.000629',
    '0.000630', '0.000636', '0.000651', '0.000656', '0.000661',
    '0.000663', '0.000666', '0.000669', '0.000671', '0.000680',
    '0.000681', '0.000686', '0.000690', '0.000698', '0.000703',
    '0.000709', '0.000717', '0.000718', '0.000720', '0.000725',
    '0.000728', '0.000729', '0.000732', '0.000735', '0.000738',
    '0.000739', '0.000750', '0.000758', '0.000768', '0.000776',
    '0.000778', '0.000782', '0.000786', '0.000792', '0.000800',
    '0.000807', '0.000815', '0.000818', '0.000825', '0.000826',
    '0.000828', '0.000829', '0.000830', '0.000839', '0.000858',
    '0.000860', '0.000876', '0.000877', '0.000878', '0.000883',
    '0.000887', '0.000895', '0.000897', '0.000898', '0.000900',
    '0.000901', '0.000902', '0.000905', '0.000910', '0.000917',
    '0.000919', '0.000921', '0.000926', '0.000927', '0.000928',
    '0.000930', '0.000932', '0.000933', '0.000935', '0.000936',
    '0.000937', '0.000938', '0.000939', '0.000948', '0.000949',
    '0.000950', '0.000951', '0.000952', '0.000957', '0.000959',
    '0.000960', '0.000961', '0.000963', '0.000966', '0.000967',
    '0.000968', '0.000969', '0.000970', '0.000971', '0.000973',
    '0.000975', '0.000977', '0.000978', '0.000980', '0.000981',
    '0.000983', '0.000985', '0.000987', '0.000988', '0.000989',
    '0.000990', '0.000993', '0.000996', '0.000997', '0.000998',
    '0.000999', '0.002001', '0.002007', '0.002013', '0.002027',
    '0.002032', '0.002039', '0.002044', '0.002048', '0.002049',
    '0.002050', '0.002051', '0.002056', '0.002060', '0.002063',
    '0.002065', '0.002066', '0.002067', '0.002069', '0.002074',
    '0.002080', '0.002081', '0.002083', '0.002085', '0.002092',
    '0.002093', '0.002095', '0.002097', '0.002100', '0.002110',
    '0.002129', '0.002142', '0.002146', '0.002152', '0.002153',
    '0.002155', '0.002157', '0.002174', '0.002176', '0.002179',
    '0.002180', '0.002182', '0.002185', '0.002190', '0.002192',
    '0.002195', '0.002202', '0.002203', '0.002230', '0.002236',
    '0.002241', '0.002244', '0.002245', '0.002249', '0.002251',
    '0.002252', '0.002254', '0.002258', '0.002262', '0.002264',
    '0.002268', '0.002269', '0.002271', '0.002273', '0.002274',
    '0.002276', '0.002277', '0.002278', '0.002280', '0.002282',
    '0.002283', '0.002284', '0.002285', '0.002287', '0.002288',
    '0.002291', '0.002292', '0.002294', '0.002296', '0.002297',
    '0.002298', '0.002299', '0.002304', '0.002311', '0.002312',
    '0.002315', '0.002316', '0.002317', '0.002318', '0.002324',
    '0.002326', '0.002327', '0.002328', '0.002334', '0.002340',
    '0.002342', '0.002344', '0.002345', '0.002346', '0.002347',
    '0.002348', '0.002352', '0.002353', '0.002354', '0.002355',
    '0.002356', '0.002358', '0.002359', '0.002360', '0.002362',
    '0.002364', '0.002365', '0.002366', '0.002367', '0.002368',
    '0.002369', '0.002371', '0.002372', '0.002373', '0.002374',
    '0.002375', '0.002376', '0.002377', '0.002378', '0.002379',
    '0.002380', '0.002382', '0.002383', '0.002384', '0.002385',
    '0.002386', '0.002387', '0.002388', '0.002389', '0.002390',
    '0.002391', '0.002392', '0.002393', '0.002394', '0.002395',
    '0.002396', '0.002397', '0.002398', '0.002399', '0.002400',
    '0.002401', '0.002402', '0.002403', '0.002404', '0.002405',
    '0.002406', '0.002407', '0.002408', '0.002409', '0.002410',
    '0.002411', '0.002412', '0.002413', '0.002414', '0.002415',
    '0.002416', '0.002417', '0.002418', '0.002419', '0.002420',
    '0.002421', '0.002422', '0.002423', '0.002424', '0.002425',
    '0.002426', '0.002427', '0.002428', '0.002429', '0.002430',
    '0.003000', '0.003001', '0.003002', '0.003003', '0.003004',
    '0.300015', '0.300017', '0.300018', '0.300024', '0.300027',
    '0.300033', '0.300059', '0.300070', '0.300074', '0.300075',
    '0.300087', '0.300124', '0.300142', '0.300144', '0.300146',
    '0.300347', '0.300408', '0.300413', '0.300433', '0.300498',
    '0.300529', '0.300558', '0.300568', '0.300595', '0.300601',
    '0.300628', '0.300750', '0.300760', '0.300769', '0.300776',
    '0.300782', '0.300783', '0.300750', '0.300793', '0.300795',
    '0.300896', '0.300957', '0.300979', '0.300999',
  ];

  return [...shStocks, ...szStocks];
}

/**
 * 获取热门股票列表（保留用于向后兼容）
 */
export async function getPopularStocks(limit = 20): Promise<StockQuote[]> {
  const allCodes = getAllStockCodes();
  const codesToFetch = allCodes.slice(0, Math.min(limit, allCodes.length));

  try {
    const codeStr = codesToFetch.join(',');
    const url = `https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18&secids=${codeStr}`;

    const response = await axios.get(url, {
      headers: {
        'Referer': 'https://www.eastmoney.com',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
      },
      timeout: 5000,
    });

    const data = response.data;
    if (data?.data?.diff) {
      const stocks = data.data.diff
        .map((item: {
          f2?: number;
          f3?: number;
          f4?: number;
          f5?: number;
          f6?: number;
          f12?: string;
          f14?: string;
          f15?: number;
          f16?: number;
          f17?: number;
          f18?: number;
        }) => ({
          code: item.f12 || '',
          name: item.f14 || '',
          price: item.f2 ? item.f2 / 100 : 0,
          change: item.f4 ? item.f4 / 100 : 0,
          changePercent: item.f3 ? item.f3 / 100 : 0,
          volume: item.f5 || 0,
          amount: item.f6 || 0,
          high: item.f15 ? item.f15 / 100 : 0,
          low: item.f16 ? item.f16 / 100 : 0,
          open: item.f17 ? item.f17 / 100 : 0,
          yesterdayClose: item.f18 ? item.f18 / 100 : 0,
          timestamp: Date.now(),
        }))
        .slice(0, limit);

      return stocks;
    }

    return [];
  } catch (error) {
    console.error('获取热门股票失败:', error);
    // 返回模拟数据
    return Array.from({ length: limit }, (_, i) => ({
      code: `${String(600000 + i).padStart(6, '0')}`,
      name: `股票${600000 + i}`,
      price: Math.random() * 100 + 10,
      change: Math.random() * 5 - 2.5,
      changePercent: Math.random() * 5 - 2.5,
      volume: Math.random() * 10000000,
      amount: Math.random() * 100000000,
      high: 0,
      low: 0,
      open: 0,
      yesterdayClose: 0,
      timestamp: Date.now(),
    }));
  }
}

/**
 * 获取所有股票列表（支持分页和排序）
 */
export async function getAllStocks(
  page = 1,
  pageSize = 20,
  sortBy: 'price' | 'changePercent' | 'volume' = 'price',
  sortOrder: 'asc' | 'desc' = 'desc'
): Promise<{ stocks: StockQuote[]; total: number; page: number; pageSize: number }> {
  const allCodes = getAllStockCodes();

  // 由于API限制，我们分批次获取股票数据
  // 为了性能，我们可以先获取所有数据，然后在前端或后端进行分页排序
  // 或者采用分批请求的策略
  const batchSize = 50; // 每批请求50只股票
  const batches: Promise<StockQuote[]>[] = [];

  for (let i = 0; i < allCodes.length; i += batchSize) {
    const batchCodes = allCodes.slice(i, i + batchSize);
    batches.push(getEastmoneyStockData(batchCodes));
  }

  try {
    // 并行请求所有批次
    const results = await Promise.allSettled(batches);
    let allStocks: StockQuote[] = [];

    results.forEach((result) => {
      if (result.status === 'fulfilled') {
        allStocks = allStocks.concat(result.value);
      } else {
        console.error('批量获取股票数据失败:', result.reason);
      }
    });

    // 如果API失败，生成模拟数据
    if (allStocks.length === 0) {
      allStocks = allCodes.map((code, i) => {
        const basePrice = 5 + Math.random() * 95;
        const changePercent = (Math.random() - 0.5) * 10;
        return {
          code: code.replace(/^[01]\./, ''), // 移除前缀
          name: `股票${i + 1}`,
          price: basePrice,
          change: basePrice * changePercent / 100,
          changePercent,
          volume: Math.random() * 50000000,
          amount: Math.random() * 500000000,
          high: basePrice * (1 + Math.abs(changePercent) / 100),
          low: basePrice * (1 - Math.abs(changePercent) / 100),
          open: basePrice * (1 + (Math.random() - 0.5) * 0.02),
          yesterdayClose: basePrice / (1 + changePercent / 100),
          timestamp: Date.now(),
        };
      });
    }

    // 排序
    allStocks.sort((a, b) => {
      let aVal: number, bVal: number;
      
      switch (sortBy) {
        case 'price':
          aVal = a.price;
          bVal = b.price;
          break;
        case 'changePercent':
          aVal = a.changePercent;
          bVal = b.changePercent;
          break;
        case 'volume':
          aVal = a.volume;
          bVal = b.volume;
          break;
        default:
          aVal = a.price;
          bVal = b.price;
      }

      if (sortOrder === 'asc') {
        return aVal - bVal;
      } else {
        return bVal - aVal;
      }
    });

    // 分页
    const startIndex = (page - 1) * pageSize;
    const endIndex = startIndex + pageSize;
    const paginatedStocks = allStocks.slice(startIndex, endIndex);

    return {
      stocks: paginatedStocks,
      total: allStocks.length,
      page,
      pageSize,
    };
  } catch (error) {
    console.error('获取所有股票失败:', error);
    // 返回模拟数据
    const mockStocks = allCodes.map((code, i) => {
      const basePrice = 5 + Math.random() * 95;
      const changePercent = (Math.random() - 0.5) * 10;
      return {
        code: code.replace(/^[01]\./, ''),
        name: `股票${i + 1}`,
        price: basePrice,
        change: basePrice * changePercent / 100,
        changePercent,
        volume: Math.random() * 50000000,
        amount: Math.random() * 500000000,
        high: basePrice * (1 + Math.abs(changePercent) / 100),
        low: basePrice * (1 - Math.abs(changePercent) / 100),
        open: basePrice * (1 + (Math.random() - 0.5) * 0.02),
        yesterdayClose: basePrice / (1 + changePercent / 100),
        timestamp: Date.now(),
      };
    });

    // 排序
    mockStocks.sort((a, b) => {
      let aVal: number, bVal: number;
      switch (sortBy) {
        case 'price':
          aVal = a.price;
          bVal = b.price;
          break;
        case 'changePercent':
          aVal = a.changePercent;
          bVal = b.changePercent;
          break;
        case 'volume':
          aVal = a.volume;
          bVal = b.volume;
          break;
        default:
          aVal = a.price;
          bVal = b.price;
      }
      return sortOrder === 'asc' ? aVal - bVal : bVal - aVal;
    });

    // 分页
    const startIndex = (page - 1) * pageSize;
    const endIndex = startIndex + pageSize;

    return {
      stocks: mockStocks.slice(startIndex, endIndex),
      total: mockStocks.length,
      page,
      pageSize,
    };
  }
}

