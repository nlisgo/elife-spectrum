for article in elife-*-???-v?; do
    for file in $article/elife*-v?.*; do
        mv "$file" "${file/-v?./.}";
    done
done
