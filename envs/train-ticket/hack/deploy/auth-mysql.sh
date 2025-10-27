for pod in $(kubectl get pods -n default --no-headers -o custom-columns=":metadata.name" | grep nacosdb-mysql); do
  echo "Processing Pod: $pod"

  # 在 mysql 容器里执行 SQL
  kubectl exec -n default $pod -- mysql -uroot -e "CREATE USER 'root'@'::1' IDENTIFIED WITH mysql_native_password BY '' ; GRANT ALL ON *.* TO 'root'@'::1' WITH GRANT OPTION ;"

  # 如果确实需要重启 xenon 容器（不是 MySQL 容器）
  kubectl exec -n default $pod -c xenon -- /sbin/reboot
done
