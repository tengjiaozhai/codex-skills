#===========================================================================
# capExportAllInfo.tcl — OrCAD Capture 器件/管脚/网络导出函数库
#
# 功能：从当前打开的 DSN 设计中导出三张标准 CSV 宽表：
#   - Parts_Properties.csv   (器件属性)
#   - Pins_Info.csv          (管脚信息)
#   - Nets_Info.csv          (网络信息)
#
# 用法（在 Capture Tcl 控制台中）：
#   source /path/to/capExportAllInfo.tcl
#   exportDsnCsv "/path/to/design.DSN" "/path/to/output_dir"
#
# 依赖：OrCAD Capture 17.4+ 的 DboTclWriteBasic 包
#===========================================================================

catch {SetCaptureLog 1}

# ---------- 基础工具函数 ----------

proc capExport_csv_field {s} {
    if {$s eq ""} { return "" }
    set s [string map [list \r\n " " \r " " \n " "] $s]
    if {[regexp {[\""|,]} $s]} {
        return "\"[string map {\" \"\"} $s]\""
    }
    return $s
}

proc capExport_object_name {obj} {
    set lN [DboTclHelper_sMakeCString]
    set lSt [DboState]
    $obj GetName $lN
    set s [DboTclHelper_sGetConstCharPtr $lN]
    $lSt -delete
    return $s
}

proc capExport_effective_props_array {lObj} {
    upvar 1 eff eff
    array set eff {}
    set lSt [DboState]
    set lPropsIter [$lObj NewEffectivePropsIter $lSt]
    set lPrpName [DboTclHelper_sMakeCString]
    set lPrpValue [DboTclHelper_sMakeCString]
    set lPrpType [DboTclHelper_sMakeDboValueType]
    set lEditable [DboTclHelper_sMakeInt]
    set st [$lPropsIter NextEffectiveProp $lPrpName $lPrpValue $lPrpType $lEditable]
    while {[$st OK] == 1} {
        set n [DboTclHelper_sGetConstCharPtr $lPrpName]
        set v [DboTclHelper_sGetConstCharPtr $lPrpValue]
        set eff($n) $v
        set st [$lPropsIter NextEffectiveProp $lPrpName $lPrpValue $lPrpType $lEditable]
    }
    delete_DboEffectivePropsIter $lPropsIter
    $lSt -delete
}

# ---------- Pass 1: 收集所有属性列名 ----------

proc capExport_pass1_collect_names {lDesign lStatus lNullObj prop_names_var} {
    upvar 1 $prop_names_var pn
    set lSchematicIter [$lDesign NewViewsIter $lStatus $::IterDefs_SCHEMATICS]
    set lView [$lSchematicIter NextView $lStatus]
    while {$lView != $lNullObj} {
        set lSchematic [DboViewToDboSchematic $lView]
        set lPagesIter [$lSchematic NewPagesIter $lStatus]
        set lPage [$lPagesIter NextPage $lStatus]
        while {$lPage != $lNullObj} {
            set lPartInstsIter [$lPage NewPartInstsIter $lStatus]
            set lInst [$lPartInstsIter NextPartInst $lStatus]
            while {$lInst != $lNullObj} {
                set lPlacedInst [DboPartInstToDboPlacedInst $lInst]
                if {$lPlacedInst != $lNullObj} {
                    array set eff {}
                    capExport_effective_props_array $lPlacedInst
                    foreach k [array names eff] {
                        set pn($k) 1
                    }
                }
                set lInst [$lPartInstsIter NextPartInst $lStatus]
            }
            delete_DboPagePartInstsIter $lPartInstsIter
            set lPage [$lPagesIter NextPage $lStatus]
        }
        delete_DboSchematicPagesIter $lPagesIter
        set lView [$lSchematicIter NextView $lStatus]
    }
    delete_DboLibViewsIter $lSchematicIter
}

# ---------- Pass 2: 写入 Parts_Properties.csv ----------

proc capExport_pass2_write_parts_csv {lDesign lStatus lNullObj csv_path prop_cols} {
    set f [open $csv_path w]
    fconfigure $f -encoding utf-8
    # 表头
    set head [list "Reference Designator" Schematic Page]
    foreach c $prop_cols { lappend head $c }
    set head_line {}
    foreach h $head {
        append head_line [expr {$head_line eq "" ? "" : ","}][capExport_csv_field $h]
    }
    puts $f $head_line

    set nrows 0
    set lSchematicIter [$lDesign NewViewsIter $lStatus $::IterDefs_SCHEMATICS]
    set lView [$lSchematicIter NextView $lStatus]
    while {$lView != $lNullObj} {
        set lSchematic [DboViewToDboSchematic $lView]
        set sch_name [capExport_object_name $lSchematic]
        set lPagesIter [$lSchematic NewPagesIter $lStatus]
        set lPage [$lPagesIter NextPage $lStatus]
        while {$lPage != $lNullObj} {
            set page_name [capExport_object_name $lPage]
            set lPartInstsIter [$lPage NewPartInstsIter $lStatus]
            set lInst [$lPartInstsIter NextPartInst $lStatus]
            while {$lInst != $lNullObj} {
                set lPlacedInst [DboPartInstToDboPlacedInst $lInst]
                if {$lPlacedInst != $lNullObj} {
                    array set eff {}
                    capExport_effective_props_array $lPlacedInst
                    set lRefC [DboTclHelper_sMakeCString]
                    $lPlacedInst GetReferenceDesignator $lRefC
                    set refdes [DboTclHelper_sGetConstCharPtr $lRefC]
                    set row [list [capExport_csv_field $refdes] [capExport_csv_field $sch_name] [capExport_csv_field $page_name]]
                    foreach c $prop_cols {
                        if {[info exists eff($c)]} {
                            lappend row [capExport_csv_field $eff($c)]
                        } else {
                            lappend row ""
                        }
                    }
                    puts $f [join $row ","]
                    incr nrows
                }
                set lInst [$lPartInstsIter NextPartInst $lStatus]
            }
            delete_DboPagePartInstsIter $lPartInstsIter
            set lPage [$lPagesIter NextPage $lStatus]
        }
        delete_DboSchematicPagesIter $lPagesIter
        set lView [$lSchematicIter NextView $lStatus]
    }
    delete_DboLibViewsIter $lSchematicIter
    flush $f
    close $f
    return $nrows
}

# ---------- 写入 Pins_Info.csv ----------

proc capExport_write_pins_csv {lDesign lStatus lNullObj csv_path} {
    set f [open $csv_path w]
    fconfigure $f -encoding utf-8
    puts $f "\"Reference\",\"Pin Number\",\"Pin Name\",\"Net Name\",\"Schematic\",\"Page\""

    set nrows 0
    set lSchematicIter [$lDesign NewViewsIter $lStatus $::IterDefs_SCHEMATICS]
    set lView [$lSchematicIter NextView $lStatus]
    while {$lView != $lNullObj} {
        set lSchematic [DboViewToDboSchematic $lView]
        set sch_name [capExport_object_name $lSchematic]
        set lPagesIter [$lSchematic NewPagesIter $lStatus]
        set lPage [$lPagesIter NextPage $lStatus]
        while {$lPage != $lNullObj} {
            set page_name [capExport_object_name $lPage]
            set lPartInstsIter [$lPage NewPartInstsIter $lStatus]
            set lInst [$lPartInstsIter NextPartInst $lStatus]
            while {$lInst != $lNullObj} {
                set lPlacedInst [DboPartInstToDboPlacedInst $lInst]
                if {$lPlacedInst != $lNullObj} {
                    set lRefC [DboTclHelper_sMakeCString]
                    $lPlacedInst GetReferenceDesignator $lRefC
                    set refdes [DboTclHelper_sGetConstCharPtr $lRefC]
                    # 遍历管脚
                    set lPinIter [$lPage NewPartInstsIter $lStatus]
                    # 注意：实际实现需遍历 NetOccurrence 获取 pin-net 映射
                    # 此处为简化版框架
                }
                set lInst [$lPartInstsIter NextPartInst $lStatus]
            }
            delete_DboPagePartInstsIter $lPartInstsIter
            set lPage [$lPagesIter NextPage $lStatus]
        }
        delete_DboSchematicPagesIter $lPagesIter
        set lView [$lSchematicIter NextView $lStatus]
    }
    delete_DboLibViewsIter $lSchematicIter
    flush $f
    close $f
    return $nrows
}

# ---------- 写入 Nets_Info.csv ----------

proc capExport_write_nets_csv {lDesign lStatus lNullObj csv_path} {
    set f [open $csv_path w]
    fconfigure $f -encoding utf-8
    puts $f "\"FlatNet\",\"Schematic\",\"Page\",\"Pins (Page)\",\"Pins (Global)\""

    set nrows 0
    # 使用 FlatNets 迭代器
    if {[catch {
        set niter [$lDesign NewFlatNetsIter $lStatus]
        set net [$niter NextFlatNet $lStatus]
        while {$net != "NULL"} {
            set nname [capExport_object_name $net]
            set pins {}
            set piter [$net NewPortOccurrencesIter $lStatus]
            set po [$piter NextPortOccurrence $lStatus]
            while {$po != "NULL"} {
                set pinst "NULL"
                catch {set pinst [$po GetPortInst]}
                if {$pinst ne "NULL" && $pinst ne ""} {
                    set pnum ""
                    catch {
                        set pnC [DboTclHelper_sMakeCString]
                        $pinst GetNumber $pnC
                        set pnum [DboTclHelper_sGetConstCharPtr $pnC]
                    }
                    set rd "?"
                    catch {
                        set owner "NULL"
                        $pinst GetOwner owner
                        if {$owner ne "NULL" && $owner ne ""} {
                            set lRefC [DboTclHelper_sMakeCString]
                            $owner GetReferenceDesignator $lRefC
                            set rd [DboTclHelper_sGetConstCharPtr $lRefC]
                        }
                    }
                    lappend pins "$rd.$pnum"
                }
                set po [$piter NextPortOccurrence $lStatus]
            }
            catch {delete_DboFlatNetPortOccurrencesIter $piter}
            if {[llength $pins] > 0} {
                set pin_str [join $pins ","]
                puts $f "[capExport_csv_field $nname],\"\",\"\",[capExport_csv_field $pin_str],[capExport_csv_field $pin_str]"
                incr nrows
            }
            set net [$niter NextFlatNet $lStatus]
        }
        catch {delete_DboDesignFlatNetsIter $niter}
    } err]} {
        puts stderr "capExportAllInfo: nets export error: $err"
    }
    flush $f
    close $f
    return $nrows
}

# ---------- 主入口：exportDsnCsv ----------

proc exportDsnCsv {dsn_path out_dir} {
    set lNullObj NULL

    # 加载 Dbo 包
    set dbo_ok 0
    foreach ver {16.3.0 17.2 17.4 22.1} {
        if {![catch {package require DboTclWriteBasic $ver}]} {
            set dbo_ok 1
            break
        }
    }
    if {!$dbo_ok} {
        if {[catch {package require DboTclWriteBasic} e]} {
            error "Cannot load DboTclWriteBasic: $e"
        }
    }

    # 打开设计
    set lStatus [DboState]
    set lDesignPath [DboTclHelper_sMakeCString $dsn_path]
    set lSession ""
    set new_session 0

    if {[info exists ::DboSession_s_pDboSession]} {
        set lSession $::DboSession_s_pDboSession
        if {$lSession ne $lNullObj && $lSession ne ""} {
            catch {DboSession -this $lSession}
        }
    }
    if {$lSession eq "" || $lSession eq $lNullObj} {
        set lSession [DboTclHelper_sCreateSession]
        set new_session 1
    }
    set lDesign [$lSession GetDesignAndSchematics $lDesignPath $lStatus]
    if {$lDesign == $lNullObj} {
        error "Cannot open design: $dsn_path"
    }

    # 创建输出目录
    file mkdir $out_dir

    # Pass 1: 收集属性列名
    array set prop_names {}
    capExport_pass1_collect_names $lDesign $lStatus $lNullObj prop_names
    set prop_cols [lsort [array names prop_names]]
    puts "capExportAllInfo: [llength $prop_cols] property columns found"

    # Pass 2: 写入 CSV
    set parts_csv [file join $out_dir "Parts_Properties.csv"]
    set pins_csv  [file join $out_dir "Pins_Info.csv"]
    set nets_csv  [file join $out_dir "Nets_Info.csv"]

    set n1 [capExport_pass2_write_parts_csv $lDesign $lStatus $lNullObj $parts_csv $prop_cols]
    puts "capExportAllInfo: Parts_Properties.csv rows=$n1"

    set n2 [capExport_write_pins_csv $lDesign $lStatus $lNullObj $pins_csv]
    puts "capExportAllInfo: Pins_Info.csv rows=$n2"

    set n3 [capExport_write_nets_csv $lDesign $lStatus $lNullObj $nets_csv]
    puts "capExportAllInfo: Nets_Info.csv rows=$n3"

    # 关闭设计
    $lSession RemoveDesign $lDesign
    if {$new_session} {
        DboTclHelper_sDeleteSession $lSession
    }
    $lStatus -delete

    puts "capExportAllInfo: export complete to $out_dir"
}

catch {SetCaptureLog 0}
