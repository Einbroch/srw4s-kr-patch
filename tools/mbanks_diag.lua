-- M_BANKS 추적 진단기 — 실패 원인을 갈라낸다
--   A) 훅 주소에 기대한 명령어가 실제로 있는가 (오버레이 적재 위치 확인)
--   B) 실행 BP가 아예 발화하는가 (레지스터 접근과 무관한 순수 카운터)
--   C) PCSX.getRegisters()가 동작하는가
-- 결과는 Logs 창이 아니라 **파일**로 쓴다: D:/srw4s_ko/diag.txt

diagLines = {}
local function say(s) diagLines[#diagLines+1] = tostring(s) end

-- C) 레지스터 API
local okr, regs = pcall(function() return PCSX.getRegisters() end)
if okr and regs then
    local okpc, pc = pcall(function() return regs.pc end)
    say("getRegisters OK  pc=" .. (okpc and string.format("0x%08X", pc) or "read-fail"))
    local okg, a0 = pcall(function() return regs.GPR.n.a0 end)
    say("GPR.n.a0 " .. (okg and string.format("0x%08X", a0) or "ACCESS FAIL"))
else
    say("getRegisters FAIL")
end

-- A) 훅 주소의 실제 명령어 (물리 오프셋으로 RAM 직접 읽기)
local okm, mem = pcall(function() return PCSX.getMemPtr() end)
if okm and mem then
    local function word(off)
        return mem[off] + mem[off+1]*256 + mem[off+2]*65536 + mem[off+3]*16777216
    end
    for _, t in ipairs({ {0x110584,0x00042203,"sra a0,a0,8 (bank)"},
                         {0x110594,0x30A500FF,"andi a1,a1,0xFF (slot)"},
                         {0x1540C4,0x94A20000,"lhu v0,(a1)"},
                         {0x1540A0,0x8C460000,"lw a2,(v0)"} }) do
        local got = word(t[1])
        say(string.format("RAM 0x%06X = %08X  기대 %08X  %s  %s",
            t[1], got, t[2], (got == t[2]) and "일치" or "불일치", t[3]))
    end
else
    say("getMemPtr FAIL")
end

-- B) 순수 카운터 BP (레지스터 접근 없음)
fireK = 0; fireP = 0
if diagBpK then pcall(function() diagBpK:remove() end) end
if diagBpP then pcall(function() diagBpP:remove() end) end
diagBpK = PCSX.addBreakpoint(0x80110594, 'Exec', 4, 'k', function() fireK = fireK + 1 return false end, 'diag kseg0')
diagBpP = PCSX.addBreakpoint(0x00110594, 'Exec', 4, 'p', function() fireP = fireP + 1 return false end, 'diag phys')
say("BP 설치: kseg0=" .. tostring(diagBpK ~= nil) .. " phys=" .. tostring(diagBpP ~= nil))

function diagDump()
    local out = {}
    for _, l in ipairs(diagLines) do out[#out+1] = l end
    out[#out+1] = "fire kseg0=" .. fireK .. "  phys=" .. fireP
    local f = io.open("D:/srw4s_ko/diag.txt", "w")
    f:write(table.concat(out, "\n") .. "\n"); f:close()
    return #out
end

diagDump()
