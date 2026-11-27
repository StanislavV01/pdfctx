def test_concurrent_reads_from_many_threads(tmp_path, report_pdf):
    from concurrent.futures import ThreadPoolExecutor

    from pdfctx.library import Library

    lib = Library(tmp_path / "i.db", roots=[report_pdf])
    (doc,) = lib.list_documents()["documents"]

    def work(i: int):
        if i % 3 == 0:
            return lib.search("revenue region", [doc["id"]], 8)
        if i % 3 == 1:
            return lib.context_pack("revenue region", 1000, [doc["id"]])
        return lib.outline(doc["id"], 4)

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(work, range(300)))  # raises if any call failed
    assert len(results) == 300
    lib.close()
