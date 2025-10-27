kill $(ps aux | grep 'run_all.sh' | grep -v grep | awk '{print $2}')
kill $(ps aux | grep 'run.sh' | grep -v grep | awk '{print $2}')
kill $(ps aux | grep 'python3' | grep -v grep | awk '{print $2}')