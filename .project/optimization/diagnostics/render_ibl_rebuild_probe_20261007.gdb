set pagination off
set confirm off
set breakpoint pending on
set $create = 0
set $destroy = 0
set $destroy_after = -1
break blunted::OpenGLRenderer3D::CreateIBLResources
commands
silent
set $create = $create + 1
continue
end
break blunted::OpenGLRenderer3D::DestroyIBLResources
commands
silent
set $destroy = $destroy + 1
set $destroy_after = $create
continue
end
run
printf "IBL_PROBE create=%d destroy=%d destroy_after=%d\n", $create, $destroy, $destroy_after
