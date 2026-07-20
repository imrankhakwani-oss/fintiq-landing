@echo off
mkdir img 2>nul
copy "Screen shots\Fundamental tab_stock screener_screenshot.png" "img\screener-1.png"
copy "Screen shots\Fundamental tab_stock screener_screenshot_2.png" "img\screener-2.png"
copy "Screen shots\Montecarlo simulation_screenshot_1.png" "img\montecarlo-1.png"
copy "Screen shots\Montecarlo simulation_screenshot_2.png" "img\montecarlo-2.png"
copy "Screen shots\Portfolio optimizer_screenshot_1.png" "img\portfolio-1.png"
copy "Screen shots\Portfolio optimizer_screenshot_3.png" "img\portfolio-2.png"
copy "Screen shots\Pair trading_screenshot_2.png" "img\pairs-1.png"
copy "Screen shots\Pair trading_screenshot_3.png" "img\pairs-2.png"
copy "Screen shots\trading journal_screenshot_1.png" "img\journal-1.png"
copy "Screen shots\morning brief_screenshot.png" "img\morning-brief-1.png"
echo.
echo All screenshots copied to img/ folder successfully.
pause
