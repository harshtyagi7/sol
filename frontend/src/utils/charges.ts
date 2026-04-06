/**
 * Zerodha brokerage and statutory charge calculator.
 * Reference: https://zerodha.com/charges
 */

export interface ChargesBreakdown {
  brokerage: number       // per side, capped at ₹20
  stt: number             // Securities Transaction Tax
  exchangeCharges: number // NSE/BSE transaction charges
  sebi: number            // SEBI turnover charges
  stampDuty: number       // Stamp duty (buy side only)
  gst: number             // 18% GST on brokerage + exchange charges
  autoSquareoffCharge: number  // ₹59 if Zerodha squared off (not Sol)
  total: number
}

/**
 * Calculate Zerodha charges for a completed trade.
 *
 * @param entryPrice   - Average buy/sell price
 * @param exitPrice    - Average close price
 * @param quantity     - Number of shares/units
 * @param direction    - 'BUY' or 'SELL' (the opening direction)
 * @param productType  - 'MIS' | 'CNC' | 'NRML'
 * @param exchange     - 'NSE' | 'BSE' | 'NFO'
 * @param isAutoSquaredOff - true if Zerodha RMS closed it (not Sol)
 */
export function calculateCharges(
  entryPrice: number,
  exitPrice: number,
  quantity: number,
  direction: string,
  productType: string,
  exchange: string,
  isAutoSquaredOff = false,
): ChargesBreakdown {
  const isFno = exchange === 'NFO' || productType === 'NRML'
  const buyPrice = direction === 'BUY' ? entryPrice : exitPrice
  const sellPrice = direction === 'BUY' ? exitPrice : entryPrice
  const buyTurnover = buyPrice * quantity
  const sellTurnover = sellPrice * quantity

  // --- Brokerage ---
  // Equity: 0.03% per side, max ₹20 per order
  // F&O: ₹20 flat per order
  let brokerage: number
  if (isFno) {
    brokerage = 20 * 2 // entry + exit
  } else {
    const brokerageRate = 0.0003
    const buyBrok = Math.min(buyTurnover * brokerageRate, 20)
    const sellBrok = Math.min(sellTurnover * brokerageRate, 20)
    brokerage = buyBrok + sellBrok
  }

  // --- STT (Securities Transaction Tax) ---
  // Equity MIS/CNC: 0.025% on sell side only
  // F&O options: 0.0625% on sell side (premium)
  // F&O futures: 0.0125% on sell side
  let stt: number
  if (isFno) {
    stt = sellTurnover * 0.000625
  } else {
    stt = sellTurnover * 0.00025
  }

  // --- Exchange Transaction Charges ---
  // NSE Equity: 0.00297% on both sides
  // NFO: 0.053% on both sides (options)
  const totalTurnover = buyTurnover + sellTurnover
  let exchangeCharges: number
  if (isFno) {
    exchangeCharges = totalTurnover * 0.00053
  } else {
    exchangeCharges = totalTurnover * 0.0000297
  }

  // --- SEBI Charges ---
  // ₹10 per crore of turnover
  const sebi = (totalTurnover / 1e7) * 10

  // --- Stamp Duty ---
  // Equity: 0.015% on buy side (MIS: 0.003%)
  // F&O: 0.002% on buy side
  let stampDuty: number
  if (isFno) {
    stampDuty = buyTurnover * 0.00002
  } else if (productType === 'MIS') {
    stampDuty = buyTurnover * 0.00003
  } else {
    stampDuty = buyTurnover * 0.00015
  }

  // --- GST ---
  // 18% on (brokerage + exchange charges + SEBI charges)
  const gst = (brokerage + exchangeCharges + sebi) * 0.18

  // --- Auto square-off charge ---
  // ₹50 + 18% GST = ₹59 if Zerodha's RMS squared off the position
  const autoSquareoffCharge = isAutoSquaredOff ? 59 : 0

  const total = brokerage + stt + exchangeCharges + sebi + stampDuty + gst + autoSquareoffCharge

  return {
    brokerage: round2(brokerage),
    stt: round2(stt),
    exchangeCharges: round2(exchangeCharges),
    sebi: round2(sebi),
    stampDuty: round2(stampDuty),
    gst: round2(gst),
    autoSquareoffCharge,
    total: round2(total),
  }
}

function round2(n: number) {
  return Math.round(n * 100) / 100
}
