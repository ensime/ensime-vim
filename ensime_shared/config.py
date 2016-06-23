gconfig = {
    "ensime_server": "ws://127.0.0.1:{}/jerky",
    "localhost": "http://127.0.0.1:{}/{}",
}

feedback = {
    "start_message": "Ensime server has been started...",
    "unknown_symbol": "Symbol not found",
    "indexer_ready": "Ensime indexer is ready",
    "analyzer_ready": "Ensime analyzer is ready",
    "typechecking": "Typechcking...",
    "module_missing": "{} missing: do a `pip install {}` and restart vim",
    "warn_classpath": "Execute :EnClasspath to set a classpath",
    "missing_debug_class": "You must specify a class to debug",
    "notify_break": "Execution breaked at {} {}",
    "displayed_type": "The type {} has been displayed",
    "failed_refactoring":
        "The refactoring could not be applied (more info at logs)",
    "unhandled_response": "Response {} has not been handled",
    "spawned_browser": "Opened tab {}",
    "manual_doc": "Go to {}"}

commands = {
    "enerror_matcher": "matchadd('EnErrorStyle', '\\%{}l\\%>{}c\\%<{}c')",
    "highlight_enerror": "highlight EnErrorStyle ctermbg=red gui=underline",
    "exists_enerrorstyle": "exists('g:EnErrorStyle')",
    "set_enerrorstyle": "let g:EnErrorStyle='EnError'",
    # http://vim.wikia.com/wiki/Timer_to_execute_commands_periodically
    # Set to low values to improve responsiveness
    "set_updatetime": "set updatetime=1000",
    "current_file": "expand('%:p')",
    "until_last_char_word": "normal e",
    "until_first_char_word": "normal b",
    # Avoid to trigger requests to server when writing
    "write_file": "noautocmd w",
    "input_save": "call inputsave()",
    "input_restore": "call inputrestore()",
    "set_input": "let user_input = input('{}')",
    "get_input": "user_input",
    "edit_file": "edit {}",
    "reload_file": "checktime",
    "display_message": "echo \"{}\"",
    "split_window": "split {}",
    "vert_split_window": "vsplit {}",
    "new_vertical_window": "{}vnew {}",
    "new_vertical_scratch": "{}vnew {} | setlocal nobuflisted buftype=nofile bufhidden=wipe noswapfile",
    "doautocmd_bufleave": "doautocmd BufLeave",
    "doautocmd_bufreadenter": "doautocmd BufReadPre,BufRead,BufEnter",
    "filetype": "&filetype",
    "set_filetype": "set filetype={}",
    "go_to_char": "goto {}",
    "set_ensime_completion": "set omnifunc=EnCompleteFunc",
    "set_quickfix_list": "call setqflist({}, '')",
    "open_quickfix": "copen",
    "disable_plugin": "set runtimepath-={}",
    "runtimepath": "&runtimepath",
    "syntastic_available": 'exists("g:SyntasticRegistry")',
    "syntastic_enable": "if exists('g:SyntasticRegistry') | let &runtimepath .= ',' . {!r} | endif",
    "syntastic_append_notes": 'if ! exists("b:ensime_scala_notes") | let b:ensime_scala_notes = [] | endif | let b:ensime_scala_notes += {}',
    "syntastic_reset_notes": 'let b:ensime_scala_notes = []',
    "syntastic_show_notes": "silent! SyntasticCheck ensime",
    "get_cursor_word": 'expand("<cword>")',
    "select_item_list": 'inputlist({})',
    "append_line": 'call append({}, {!r})',
    "redraw": "redraw!"
}
