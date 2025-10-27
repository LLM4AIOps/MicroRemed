bash stop_chaos.sh train-ticket
python3 inject_and_remediate.py \
  --experiments 50 \
  --namespace train-ticket \
  --wait-interval 10 \
  --injection-timeout 60 \
  --env train-ticket \
  --save-path conversations \
  --manifest-path envs/source-config/train-ticket-config.yaml \
  --remediate-method SoloGen \
  --experiment-path experiments/easy.txt \
  --model qwen-plus
