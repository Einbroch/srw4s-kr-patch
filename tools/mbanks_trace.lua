-- SRW4S M_BANKS 도달 추적기 (PCSX-Redux Lua 콘솔에서 실행)
--
-- 훅: MAP 해제물 0x0A214 = RAM 0x80110594  `andi $a1,$a1,0xFF`
--     이 명령 직전에 $a0 = 뱅크(sra $a0,$a0,8 결과), $a1 = 슬롯이 될 값이다.
--     invoker가 false를 반환하므로 에뮬레이터는 멈추지 않는다 — 평소처럼 플레이하면 된다.
--
-- 사용법
--   1) Redux 메뉴에서 Lua 콘솔을 열고 이 파일 내용을 붙여넣는다
--   2) 평소처럼 플레이한다 (대사가 나올수록 표본이 쌓인다)
--   3) 콘솔에서  traceStats()   진행 확인
--   4) 콘솔에서  dumpTrace()    파일로 저장

local HOOK_KSEG0 = 0x80110594
local HOOK_PHYS  = 0x00110594     -- Redux가 물리 주소로 볼 경우 대비, 둘 다 건다

seenSlots = seenSlots or {}
traceHits = traceHits or 0

local band = (bit and bit.band) or function(a, b) return a % (b + 1) end

local function onHit(address, width, cause)
    local ok, r = pcall(function() return PCSX.getRegisters().GPR.n end)
    if ok and r then
        local key = string.format("%d:%d", band(r.a0, 0xFF), band(r.a1, 0xFF))
        seenSlots[key] = (seenSlots[key] or 0) + 1
        traceHits = traceHits + 1
    end
    return false          -- 멈추지 않는다
end

if traceBpA then pcall(function() traceBpA:remove() end) end
if traceBpB then pcall(function() traceBpB:remove() end) end
traceBpA = PCSX.addBreakpoint(HOOK_KSEG0, 'Exec', 4, 'mbanks', onHit, 'MBANKS slot (kseg0)')
traceBpB = PCSX.addBreakpoint(HOOK_PHYS,  'Exec', 4, 'mbanks', onHit, 'MBANKS slot (phys)')

function traceStats()
    local n = 0
    for _ in pairs(seenSlots) do n = n + 1 end
    PCSX.log(string.format("[mbanks] 고유 슬롯 %d개 / 히트 %d회", n, traceHits))
    return n, traceHits
end

function dumpTrace(path)
    path = path or "D:/srw4s_ko/mbanks_trace.tsv"
    local lines = { "bank\tslot\thits" }
    local n = 0
    for k, c in pairs(seenSlots) do
        local b, s = k:match("^(%d+):(%d+)$")
        lines[#lines + 1] = b .. "\t" .. s .. "\t" .. c
        n = n + 1
    end
    local body = table.concat(lines, "\n") .. "\n"
    local f = io.open and io.open(path, "w")
    if f then
        f:write(body); f:close()
        PCSX.log(string.format("[mbanks] %d개 슬롯을 %s 에 저장", n, path))
    else
        PCSX.log("[mbanks] 파일 저장 불가 — 아래 내용을 복사하라")
        PCSX.log(body)
    end
    return n
end

function resetTrace()
    seenSlots = {}; traceHits = 0
    PCSX.log("[mbanks] 초기화")
end

PCSX.log("[mbanks] 추적기 설치 완료. 플레이 후 traceStats() / dumpTrace()")
