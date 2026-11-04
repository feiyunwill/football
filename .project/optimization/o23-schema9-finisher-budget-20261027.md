# O23 schema9 finisher budget

The audited seed-42 pilot projected 2,617.687 seconds for 8,192 updates. Each fresh training seed receives `ceil((projection * 1.05 + 120) / 60) * 60 = 2,880` seconds. The five-seed total cap is 14,400 seconds. Checkpoints are registered through update 8,192 so a stopped run leaves diagnostic evidence without selecting a candidate.

The study uses the existing frozen O23 acceptance gates. It opens no prospective or confirmation cases and cannot enable O24 or O25.