###############################################################################
# 脚本名称: capExportAllInfo.tcl
# 功能: 导出OrCAD Capture设计中的器件属性、网络、管脚到 CSV（Nets_Info 首列为 FlatNet 名；无 Flat 端口映射时与管脚聚合一致退回页内逻辑名，避免空表；Pins_Info Net Name 仍为页内逻辑名）
# 位号：优先有效属性「Part Reference」/「Gate」等多 section 信息；全设计内仍重复时第 2 次起加 @页名
# CSV 不写「# Schematic」分隔行，避免被 Excel 当成数据行
# 使用说明:
# 1. 在Capture TCL命令窗口中执行: source [file normalize {脚本路径/capExportAllInfo.tcl}]
# 2. 执行命令: ::capExport::exportAllInfo <设计文件路径> <输出目录>
#    简短命令: exportDsnCsv <.dsn路径> <输出目录>（与上式等效；勿用 interp alias 以免 source 回显）
#    详细日志: set ::capExport::exportVerbose 1 后再导出；默认 0 静默
#    例如: ::capExport::exportAllInfo "G:/CaptureData/SIGXP1.DSN" "C:/Exports"
# 对照文档: 《OrCAD Capture Tcl/Tk Extensions》Application Notes（如 Rev 1.2）
#   - 3.2.2/3.2.3/3.2.4：会话、CreateSession、GetDesignAndSchematics（实例方法）
#   - 3.2.7/3.2.9/3.2.10/3.2.12：原理图迭代、页迭代、器件实例、导线
#   - 3.2.21/3.2.24：用户属性 GetStringValue、有效属性 NextEffectiveProp（四参）
#   - 官方批处理示例（caprev.tcl）：package require TCL 8.4、DboSession_RemoveDesign、delete_DboSession
# DboTclWriteBasic 版本随安装变化；失败时在 Capture 中执行: package versions DboTclWriteBasic
# 会话日志与 puts 使用英文 ASCII：Capture Tcl 在中文 Windows 上常按系统代码页显示，UTF-8 中文会乱码。文件头注释可仍为中文。
###############################################################################

# 与文档示例一致：手册写 package require TCL 8.4（大写 TCL）
if {[catch {package require TCL 8.4}]} {
    package require Tcl 8.4
}

# 须先于 proc ::capExport::... 存在，否则 Tcl 报 unknown namespace（puts 过滤与后续 namespace eval 共用此空间）
namespace eval ::capExport {}

# Capture 在 package require DboTclWriteBasic 时常 puts「Ignored explicit loading of orDB_Dll…」；加载期间临时过滤
proc ::capExport::_putsFilterInstall {} {
    if {[llength [info commands ::capExport::_puts_orig]]} {
        return
    }
    rename ::puts ::capExport::_puts_orig
    proc ::puts args {
        if {[llength $args]} {
            set _t [join $args]
            if {[string match *orDB_Dll* $_t] && [string match {*Ignored explicit*} $_t]} {
                return
            }
        }
        uplevel 1 [linsert $args 0 ::capExport::_puts_orig]
    }
}
proc ::capExport::_putsFilterRemove {} {
    if {[llength [info commands ::capExport::_puts_orig]]} {
        rename ::puts {}
        rename ::capExport::_puts_orig ::puts
    }
}
::capExport::_putsFilterInstall
set _capExport_pkgErr [catch {
    set _capExport_dbo_ok 0
    foreach _capExport_ver {16.3.0 17.2 17.4 22.1} {
        if {![catch {package require DboTclWriteBasic $_capExport_ver}]} {
            set _capExport_dbo_ok 1
            break
        }
    }
    if {!$_capExport_dbo_ok} {
        package require DboTclWriteBasic
    }
} _capExport_pkgMsg]
::capExport::_putsFilterRemove
if {$_capExport_pkgErr} {
    error $_capExport_pkgMsg
}
unset -nocomplain _capExport_dbo_ok _capExport_ver _capExport_pkgErr _capExport_pkgMsg
package provide capExport 1.0

namespace eval ::capExport {
    namespace export exportAllInfo
    namespace export exportActiveDesign
    
    variable mExportPath ""
    # 器件宽表：有效属性列名（全设计扫描后排序）
    variable mPartWideColNames {}
    # 为 1 时在 FlatNet 上补充管脚行（Pins_Info）；聚合键第三段为 FlatNet 名；页键与空原理图/页桶在 Pin 列中合并
    variable pinsAppendFlatNets 1
    # 保留变量位（当前 Nets 首列与管脚聚合统一用 _netAggKeyName：有映射为 Flat，否则为页内逻辑名）
    variable netsOnlyMappedFlatNetRows 1
    # 为 1 时在控制台/会话日志输出进度与成功摘要；默认 0 静默
    variable exportVerbose 0
}

# 仅当 exportVerbose=1 时写入会话并 puts（错误路径仍直接 puts，不经过此过程）
proc ::capExport::_logInfo {msg} {
    if {!$::capExport::exportVerbose} {
        return
    }
    set s [DboTclHelper_sMakeCString $msg]
    catch {DboState_WriteToSessionLog $s}
    puts [DboTclHelper_sGetConstCharPtr $s]
}

# 3.2.2：当前 Capture 会话；兼容 DboTclHelper_GetSession / 大小写变体全局名（见同仓库 export_snapshot.tcl 说明）
proc ::capExport::_captureSession {} {
    set lNull NULL
    if {[llength [info commands DboTclHelper_GetSession]]} {
        if {![catch {DboTclHelper_GetSession} sess]} {
            if {$sess ne "" && $sess ne "NULL" && $sess ne $lNull} {
                return $sess
            }
        }
    }
    foreach gv {::DboSession_s_pDboSession ::dboSession_s_pDboSession} {
        if {[info exists $gv]} {
            set sess [set $gv]
            if {$sess ne "" && $sess ne "NULL" && $sess ne $lNull} {
                return $sess
            }
        }
    }
    return ""
}

proc ::capExport::_deleteCreatedSession {sess} {
    if {$sess eq ""} {
        return
    }
    # caprev.tcl：delete_DboSession；部分环境仅有 DboTclHelper_sDeleteSession（勿连续调用以免重复释放）
    if {[llength [info commands delete_DboSession]]} {
        catch {delete_DboSession $sess}
    } elseif {[llength [info commands DboTclHelper_sDeleteSession]]} {
        catch {DboTclHelper_sDeleteSession $sess}
    }
}

proc ::capExport::_removeDesignFromSession {sess des} {
    set lNull NULL
    if {$sess eq "" || $des eq "" || $des eq $lNull || $des eq "NULL"} {
        return
    }
    if {[llength [info commands DboSession_RemoveDesign]]} {
        catch {DboSession_RemoveDesign $sess $des}
    } else {
        catch {$sess RemoveDesign $des}
    }
}

# 创建CSV文件并写入表头
proc ::capExport::createCSVFile {fileName header} {
    set filePath [file join $::capExport::mExportPath $fileName]
    set parent [file dirname $filePath]
    if {![file exists $parent]} {
        file mkdir $parent
    }
    set fileId [open $filePath w]
    fconfigure $fileId -encoding utf-8 -translation lf -buffering line
    puts $fileId $header
    return $fileId
}

# 关闭 CSV（异常退出时也必须调用，否则会一直被 Capture 占用）
proc ::capExport::closeCSVFile {fileId} {
    if {$fileId eq ""} {
        return
    }
    catch {flush $fileId}
    catch {close $fileId}
}

# 网络/线段等对象取逻辑名（部分绑定 GetName 出参为空时需试 GetNetName）
proc ::capExport::dboObjectNameStr {dbo} {
    if {$dbo eq "" || $dbo eq "NULL"} {
        return ""
    }
    if {[llength [info commands DboTclHelper_sMakeCString]]} {
        if {![catch {
            set c [DboTclHelper_sMakeCString]
            $dbo GetName $c
            set t [DboTclHelper_sGetConstCharPtr $c]
        }]} {
            set t [string trim $t]
            if {$t ne ""} {
                return $t
            }
        }
        if {![catch {
            set c2 [DboTclHelper_sMakeCString]
            $dbo GetNetName $c2
            set t2 [DboTclHelper_sGetConstCharPtr $c2]
        }]} {
            set t2 [string trim $t2]
            if {$t2 ne ""} {
                return $t2
            }
        }
    }
    return ""
}

# 单 CString 出参方法（如 PortInst GetNumber / GetReferenceDesignator）
proc ::capExport::dboObjOneString {obj method} {
    if {$obj eq "" || $obj eq "NULL"} {
        return ""
    }
    if {![catch {
        set c [DboTclHelper_sMakeCString]
        $obj $method $c
        set t [DboTclHelper_sGetConstCharPtr $c]
    }]} {
        return [string trim $t]
    }
    return ""
}

# FlatNet 端口所属实例位号
proc ::capExport::flatPortOwnerRefDes {owner lNullObj} {
    set t [::capExport::dboObjOneString $owner GetReferenceDesignator]
    if {$t ne ""} {
        return $t
    }
    return "?"
}

# 管脚聚合键：原理图名 + 页名 + 网名（第三段为 FlatNet 名；ASCII 0x1e 分隔）
proc ::capExport::_aggNetPinKey {sch pg netNm} {
    return "[string trim $sch]\x1e[string trim $pg]\x1e[string trim $netNm]"
}

# 由 FlatNet 遍历建立的映射：页内「逻辑网名」-> FlatNet 名（别名合并）
proc ::capExport::_flatNameForLocalNet {sch pg localNm} {
    set loc [string trim $localNm]
    if {$loc eq ""} {
        return ""
    }
    set k [::capExport::_aggNetPinKey $sch $pg $loc]
    if {[info exists ::capExport::_localNetFlatName($k)]} {
        return [string trim $::capExport::_localNetFlatName($k)]
    }
    return ""
}

# 聚合/导出用网名：优先 FlatNet，无映射时退回页内逻辑名
proc ::capExport::_flatOrLocalNetName {sch pg localNm} {
    set f [::capExport::_flatNameForLocalNet $sch $pg $localNm]
    if {$f eq ""} {
        set f [::capExport::_flatNameForLocalNet "" "" $localNm]
    }
    if {$f eq ""} {
        return [string trim $localNm]
    }
    return [string trim $f]
}

# 仅 FlatNet 映射名（无映射返回空），用于 Nets_Info 首列以与 Capture FlatNet 条数对齐
proc ::capExport::_flatNameStrictForNetsCsv {sch pg localNm} {
    set f [::capExport::_flatNameForLocalNet $sch $pg $localNm]
    if {$f eq ""} {
        set f [::capExport::_flatNameForLocalNet "" "" $localNm]
    }
    return [string trim $f]
}

# 管脚聚合第三段：有 Flat 映射用 Flat，否则用页内逻辑名（保证管脚仍入账）
proc ::capExport::_netAggKeyName {sch pg localNm} {
    set t [::capExport::_flatNameStrictForNetsCsv $sch $pg $localNm]
    if {$t ne ""} {
        return $t
    }
    return [string trim $localNm]
}

# Nets_Info 首列与管脚聚合第三段一致：有 Flat 映射用 Flat，否则用页内逻辑名（避免仅「严格 Flat」时整表无行）
proc ::capExport::_netsRowFlatLabel {sch pg localNm} {
    return [::capExport::_netAggKeyName $sch $pg $localNm]
}

# Nets 行首列：优先从标量网对象取 FlatNet（与 Capture 浏览器「Net Name」列一致），避免多个 Object ID/OffPage 别名被当成不同网
# args：若干 DboNet 等对象，按顺序尝试 GetFlatNet
proc ::capExport::_netsRowLabelFromNetObjs {sch pg localNmStr lStatus lNullObj args} {
    foreach netObj $args {
        if {$netObj eq "" || $netObj eq "NULL" || $netObj == $lNullObj} {
            continue
        }
        set fo [::capExport::flatNetNameFromScalarNet $netObj $lStatus $lNullObj]
        if {$fo ne ""} {
            set loc [string trim $localNmStr]
            if {$loc ne "" && $loc ne $fo} {
                ::capExport::_flatMapSetAlias $sch $pg $loc $fo
            }
            return $fo
        }
    }
    return [::capExport::_netsRowFlatLabel $sch $pg $localNmStr]
}

# 在导出管脚前调用：遍历 FlatNet 端口，建立 (原理图,页,本地网名)->FlatNet 名
proc ::capExport::buildLocalNetToFlatMap {pDesign lStatus lNullObj} {
    catch {array unset ::capExport::_localNetFlatName}
    array set ::capExport::_localNetFlatName {}
    catch {array unset ::capExport::_officialFlatNet}
    array set ::capExport::_officialFlatNet {}
    if {[catch {
        set niter [$pDesign NewFlatNetsIter $lStatus]
        if {$niter eq $lNullObj || $niter eq ""} {
            catch {delete_DboDesignFlatNetsIter $niter}
            catch {delete_DboFlatNetsIter $niter}
            return
        }
        set fnet [$niter NextFlatNet $lStatus]
        while {$fnet != $lNullObj} {
            set flatNm [string trim [::capExport::dboObjectNameStr $fnet]]
            if {$flatNm ne ""} {
                set ::capExport::_officialFlatNet($flatNm) 1
            }
            if {[catch {set piter [$fnet NewPortOccurrencesIter $lStatus]}]} {
                set fnet [$niter NextFlatNet $lStatus]
                continue
            }
            if {$piter eq $lNullObj || $piter eq ""} {
                set fnet [$niter NextFlatNet $lStatus]
                continue
            }
            set po [$piter NextPortOccurrence $lStatus]
            while {$po != $lNullObj} {
                set pinst $lNullObj
                if {![catch {set pinst [$po GetPortInst]}]} {
                } elseif {![catch {$po GetPortInst pinst}]} {
                } elseif {![catch {set pinst [$po GetPinInst]}]} {
                } elseif {![catch {$po GetPinInst pinst}]} {
                }
                if {$pinst eq "" || $pinst eq "NULL" || $pinst == $lNullObj} {
                    set po [$piter NextPortOccurrence $lStatus]
                    continue
                }
                set owner $lNullObj
                if {![catch {$pinst GetOwner owner}]} {
                } elseif {![catch {set owner [$pinst GetOwner $lStatus]}]} {
                } elseif {![catch {set owner [$pinst GetOwner]}]} {
                }
                set fsch ""
                set fpg ""
                if {$owner ne "" && $owner ne "NULL" && $owner != $lNullObj} {
                    set _sp [::capExport::dboSchPageNamesForGraphicalObj $owner $lStatus $lNullObj]
                    set fsch [lindex $_sp 0]
                    set fpg [lindex $_sp 1]
                }
                if {$fsch eq "" && $fpg eq "" && $pinst ne "" && $pinst ne "NULL" && $pinst != $lNullObj} {
                    set _sp2 [::capExport::dboSchPageNamesForGraphicalObj $pinst $lStatus $lNullObj]
                    set fsch [lindex $_sp2 0]
                    set fpg [lindex $_sp2 1]
                }
                set localNm [::capExport::pinGetNetName $pinst $lStatus $lNullObj]
                if {[string trim $localNm] eq ""} {
                    set localNm [::capExport::portOccLocalNetName $po $pinst $lStatus $lNullObj]
                }
                set loc [string trim $localNm]
                if {$loc ne "" && $flatNm ne ""} {
                    ::capExport::_flatMapSetAlias $fsch $fpg $loc $flatNm
                }
                set po [$piter NextPortOccurrence $lStatus]
            }
            catch {delete_DboFlatNetPortOccurrencesIter $piter}
            catch {delete_DboPortOccurrencesIter $piter}
            set fnet [$niter NextFlatNet $lStatus]
        }
        catch {delete_DboDesignFlatNetsIter $niter}
        catch {delete_DboFlatNetsIter $niter}
        ::capExport::_logInfo "capExport: FlatNet names from iter [array size ::capExport::_officialFlatNet], alias-map keys [array size ::capExport::_localNetFlatName]"
    } err]} {
        puts "capExport buildLocalNetToFlatMap: $err"
    }
}

# 全设计按 FlatNet 名聚合管脚（供 Nets_Info「Pins (Global)」列）
proc ::capExport::_aggGlobalNetPinAdd {netNm refDes pnum} {
    set rd [string trim $refDes]
    set pn [string trim $pnum]
    if {$rd eq ""} { set rd "?" }
    if {$pn eq ""} { set pn "?" }
    set tok "${rd}.${pn}"
    set nn [string trim $netNm]
    if {![info exists ::capExport::_aggGlobalNetPins($nn)]} {
        set ::capExport::_aggGlobalNetPins($nn) {}
    }
    set cur $::capExport::_aggGlobalNetPins($nn)
    if {[lsearch -exact $cur $tok] < 0} {
        lappend ::capExport::_aggGlobalNetPins($nn) $tok
    }
}

proc ::capExport::_aggGlobalNetPinJoinStr {netNm} {
    set nn [string trim $netNm]
    if {![info exists ::capExport::_aggGlobalNetPins($nn)]} {
        return ""
    }
    set plist $::capExport::_aggGlobalNetPins($nn)
    if {![llength $plist]} {
        return ""
    }
    return [join [lsort -dictionary $plist] ,]
}

# 将管脚记入按「原理图+页+网」聚合的缓冲，并记入全设计按网名聚合（供 Nets_Info）
proc ::capExport::_aggNetPinAdd {sch pg netNm refDes pnum} {
    set rd [string trim $refDes]
    set pn [string trim $pnum]
    if {$rd eq ""} { set rd "?" }
    if {$pn eq ""} { set pn "?" }
    set tok "${rd}.${pn}"
    set key [::capExport::_aggNetPinKey $sch $pg $netNm]
    if {![info exists ::capExport::_aggNetPins($key)]} {
        set ::capExport::_aggNetPins($key) {}
    }
    set cur $::capExport::_aggNetPins($key)
    if {[lsearch -exact $cur $tok] < 0} {
        lappend ::capExport::_aggNetPins($key) $tok
    }
    ::capExport::_aggGlobalNetPinAdd $netNm $rd $pn
}

# 同一原理图+页+网名在 Nets_Info 只写一行（多段导线去重）
proc ::capExport::_netsEmitRowIfNew {fileId lNetName sch pg pinPage pinGlobal} {
    set rk [::capExport::_aggNetPinKey $sch $pg $lNetName]
    if {[info exists ::capExport::_netCsvRowEmitted($rk)]} {
        return
    }
    set ::capExport::_netCsvRowEmitted($rk) 1
    puts $fileId [::capExport::csvRow [list $lNetName $sch $pg $pinPage $pinGlobal]]
}

proc ::capExport::_aggNetPinJoinStr {sch pg netNm} {
    set nn [string trim $netNm]
    array set U {}
    set out {}
    set kPage [::capExport::_aggNetPinKey $sch $pg $nn]
    set kFlat [::capExport::_aggNetPinKey "" "" $nn]
    foreach k [list $kPage $kFlat] {
        if {![info exists ::capExport::_aggNetPins($k)]} {
            continue
        }
        foreach x $::capExport::_aggNetPins($k) {
            if {![info exists U($x)]} {
                set U($x) 1
                lappend out $x
            }
        }
    }
    if {![llength $out]} {
        return ""
    }
    return [join [lsort -dictionary $out] ,]
}

# 文档 3.2.20：全设计 FlatNet + PortOccurrence，追加管脚行；尽量解析原理图/页写入聚合键，使 Nets_Info 的 Pin 列含 Flat 脚
proc ::capExport::appendFlatNetPinRows {pDesign fileId lStatus lNullObj} {
    variable pinsAppendFlatNets
    if {!$pinsAppendFlatNets} {
        return
    }
    if {[catch {
        set niter [$pDesign NewFlatNetsIter $lStatus]
        if {$niter eq $lNullObj || $niter eq ""} {
            catch {delete_DboDesignFlatNetsIter $niter}
            catch {delete_DboFlatNetsIter $niter}
            return
        }
        set net [$niter NextFlatNet $lStatus]
        while {$net != $lNullObj} {
            set nname [string trim [::capExport::dboObjectNameStr $net]]
            if {[catch {set piter [$net NewPortOccurrencesIter $lStatus]}]} {
                set net [$niter NextFlatNet $lStatus]
                continue
            }
            if {$piter eq $lNullObj || $piter eq ""} {
                set net [$niter NextFlatNet $lStatus]
                continue
            }
            set po [$piter NextPortOccurrence $lStatus]
            while {$po != $lNullObj} {
                set pinst $lNullObj
                if {![catch {set pinst [$po GetPortInst]}]} {
                } elseif {![catch {$po GetPortInst pinst}]} {
                } elseif {![catch {set pinst [$po GetPinInst]}]} {
                } elseif {![catch {$po GetPinInst pinst}]} {
                }
                if {$pinst eq "" || $pinst eq "NULL" || $pinst == $lNullObj} {
                    set po [$piter NextPortOccurrence $lStatus]
                    continue
                }
                set owner $lNullObj
                if {![catch {$pinst GetOwner owner}]} {
                } elseif {![catch {set owner [$pinst GetOwner $lStatus]}]} {
                } elseif {![catch {set owner [$pinst GetOwner]}]} {
                }
                set rd [::capExport::flatPortOwnerRefDes $owner $lNullObj]
                set pnum [::capExport::dboObjOneString $pinst GetNumber]
                if {$pnum eq ""} {
                    set pnum [::capExport::dboObjOneString $pinst GetPinNumber]
                }
                if {$pnum eq ""} {
                    set pnum [::capExport::dboObjOneString $pinst GetDesignator]
                }
                set pnm $pnum
                if {$pnum eq ""} {
                    set pnum "?"
                    set pnm "?"
                }
                set fsch ""
                set fpg ""
                if {$owner ne "" && $owner ne "NULL" && $owner != $lNullObj} {
                    set _sp [::capExport::dboSchPageNamesForGraphicalObj $owner $lStatus $lNullObj]
                    set fsch [lindex $_sp 0]
                    set fpg [lindex $_sp 1]
                }
                if {$fsch eq "" && $fpg eq "" && $pinst ne "" && $pinst ne "NULL" && $pinst != $lNullObj} {
                    set _sp2 [::capExport::dboSchPageNamesForGraphicalObj $pinst $lStatus $lNullObj]
                    set fsch [lindex $_sp2 0]
                    set fpg [lindex $_sp2 1]
                }
                if {$fsch eq "" && $fpg eq ""} {
                    ::capExport::_aggNetPinAdd "" "" $nname $rd $pnum
                } else {
                    ::capExport::_aggNetPinAdd $fsch $fpg $nname $rd $pnum
                }
                puts $fileId [::capExport::csvRowPinRecord $rd $pnum $pnm $nname $fsch $fpg]
                set po [$piter NextPortOccurrence $lStatus]
            }
            catch {delete_DboFlatNetPortOccurrencesIter $piter}
            catch {delete_DboPortOccurrencesIter $piter}
            set net [$niter NextFlatNet $lStatus]
        }
        catch {delete_DboDesignFlatNetsIter $niter}
        catch {delete_DboFlatNetsIter $niter}
    } err]} {
        puts "capExport appendFlatNetPinRows: $err"
    }
}

# 判断导线段所属网络是否与 $lNet 为同一对象（== 在部分 Tcl 绑定下不可靠，辅以字符串与网名比对）
proc ::capExport::_wireNetSameAs {lWireNet lNet lNetName lStatus lNullObj} {
    if {$lWireNet eq "" || $lWireNet eq $lNullObj} {
        return 0
    }
    if {$lWireNet == $lNet} {
        return 1
    }
    if {[string equal [format {%s} $lWireNet] [format {%s} $lNet]]} {
        return 1
    }
    if {$lNetName ne ""} {
        set wn [::capExport::dboObjectNameStr $lWireNet]
        if {[string equal $wn $lNetName]} {
            return 1
        }
    }
    return 0
}

# Excel 打开 CSV 时常把「0201」「0402」等当成数值并吃掉前导 0；前加制表符可强制按文本显示
proc ::capExport::csvCellExcelText {s} {
    if {$s eq ""} {
        return $s
    }
    if {[string match "\t*" $s]} {
        return $s
    }
    if {[regexp {^0[0-9]} $s]} {
        return "\t$s"
    }
    if {[regexp {^[0-9]+$} [string trim $s]]} {
        return "\t$s"
    }
    return $s
}

# CSV 一行：所有字段转字符串并转义双引号（值中含逗号也可被 Excel 正确分列）
proc ::capExport::csvRow {fieldList} {
    set parts {}
    foreach f $fieldList {
        set fx [::capExport::csvCellExcelText $f]
        lappend parts "\"[string map {\" \"\"} $fx]\""
    }
    return [join $parts ,]
}

# 宽表一行：固定列 + 按 mPartWideColNames 顺序从 effList 取值
proc ::capExport::csvRowPartWide {disp sch pg val lib fp x y rot effList wideCols} {
    array unset _pv
    array set _pv $effList
    set row [list $disp $sch $pg $val $lib $fp $x $y $rot]
    foreach c $wideCols {
        if {[info exists _pv($c)]} {
            lappend row $_pv($c)
        } else {
            lappend row {}
        }
    }
    return [::capExport::csvRow $row]
}

# 从有效属性 + 底数位号得到导出用位号（多 section：优先 Part Reference，其次 Gate 等）
proc ::capExport::displayRefDesFromEffList {baseRef pairList} {
    array unset _e
    array set _e $pairList
    set b [string trim $baseRef]
    foreach pk {{Part Reference} {Part Ref} RefDes Reference} {
        if {[info exists _e($pk)]} {
            set v [string trim $_e($pk)]
            if {$v ne ""} { return $v }
        }
    }
    foreach gk {Gate GATE {Package Gate} Section {Package Section}} {
        if {[info exists _e($gk)]} {
            set g [string trim $_e($gk)]
            if {$g eq ""} { continue }
            if {$b eq ""} { return $g }
            if {[string match $b* $g]} { return $g }
            if {[regexp {^[A-Za-z0-9]$} $g]} { return "${b}$g" }
            return "${b}:${g}"
        }
    }
    return $b
}

# 同一设计内导出位号字符串重复时，第 2 次及以后追加 @页名（无页名则用 #序号）
proc ::capExport::_disambiguateRefDes {disp pageName} {
    set d [string trim $disp]
    if {$d eq ""} { return $d }
    set k [string tolower $d]
    if {![info exists ::capExport::_refExportSeen($k)]} {
        set ::capExport::_refExportSeen($k) 0
    }
    incr ::capExport::_refExportSeen($k)
    set n $::capExport::_refExportSeen($k)
    if {$n == 1} {
        return $d
    }
    set pg [string trim $pageName]
    if {$pg ne ""} {
        return "${d}@${pg}"
    }
    return "${d}#${n}"
}

# 收集 DboPlacedInst 有效属性 → list（供 array set / 格式化）
proc ::capExport::placedInstEffectivePropsList {placedInst lNullObj lStatus} {
    array set eff {}
    set lEffPropsIter ""
    if {[catch {
        set lEffPropsIter [$placedInst NewEffectivePropsIter $lStatus]
        if {$lEffPropsIter ne $lNullObj && $lEffPropsIter ne ""} {
            set lPrpName [DboTclHelper_sMakeCString]
            set lPrpValue [DboTclHelper_sMakeCString]
            set lPrpType [DboTclHelper_sMakeDboValueType]
            set lEditable [DboTclHelper_sMakeInt]
            set lDeletable [DboTclHelper_sMakeInt]
            set lStatus2 [::capExport::effectivePropNext $lEffPropsIter $lPrpName $lPrpValue $lPrpType $lEditable $lDeletable]
            while {[$lStatus2 OK] == 1} {
                set n [DboTclHelper_sGetConstCharPtr $lPrpName]
                set v [DboTclHelper_sGetConstCharPtr $lPrpValue]
                if {$n ne ""} { set eff($n) $v }
                set lStatus2 [::capExport::effectivePropNext $lEffPropsIter $lPrpName $lPrpValue $lPrpType $lEditable $lDeletable]
            }
            delete_DboEffectivePropsIter $lEffPropsIter
            set lEffPropsIter ""
        }
    } err]} {
        if {$lEffPropsIter ne "" && $lEffPropsIter ne $lNullObj} {
            catch {delete_DboEffectivePropsIter $lEffPropsIter}
        }
        puts "capExport placedInstEffectivePropsList: $err"
    }
    return [array get eff]
}

# 3.2.24：NextEffectiveProp 为四参（Name/Value/Type/Editable）；部分版本绑定含 Deletable 为第五参
proc ::capExport::effectivePropNext {pIter pName pVal pType pEditable pDeletable} {
    if {![info exists ::capExport::_effDel]} {
        if {[catch {$pIter NextEffectiveProp $pName $pVal $pType $pEditable} st]} {
            if {[string match *wrong*args* [string tolower $st]]} {
                set ::capExport::_effDel 1
                return [$pIter NextEffectiveProp $pName $pVal $pType $pEditable $pDeletable]
            }
            return -code error $st
        }
        set ::capExport::_effDel 0
        return $st
    }
    if {$::capExport::_effDel} {
        return [$pIter NextEffectiveProp $pName $pVal $pType $pEditable $pDeletable]
    }
    return [$pIter NextEffectiveProp $pName $pVal $pType $pEditable]
}

# SPB 17.4：NewPagesIter 常见返回 SchPage/代理句柄，仅有 NewWiresInAreaIter 等；需换为可 NewPartInstsIter 的页
proc ::capExport::drawingPageFrom {pPage lStatus} {
    set lNullObj NULL
    if {[catch {$pPage NewPartInstsIter $lStatus} probe] == 0} {
        if {$probe ne $lNullObj && $probe ne ""} {
            delete_DboPagePartInstsIter $probe
        }
        return $pPage
    }
    set walker $pPage
    for {set depth 0} {$depth < 6} {incr depth} {
        if {[catch {$walker GetOwner} own]} {
            break
        }
        if {$own eq "" || $own eq $lNullObj} {
            break
        }
        set walker $own
        if {[catch {$walker NewPartInstsIter $lStatus} probeOw] == 0} {
            if {$probeOw ne $lNullObj && $probeOw ne ""} {
                delete_DboPagePartInstsIter $probeOw
            }
            return $walker
        }
    }
    if {[catch {$pPage GetContents} gc] == 0} {
        if {$gc ne $lNullObj && $gc ne ""} {
            if {[catch {$gc NewPartInstsIter $lStatus} probe2] == 0} {
                if {$probe2 ne $lNullObj && $probe2 ne ""} {
                    delete_DboPagePartInstsIter $probe2
                }
                return $gc
            }
        }
    }
    foreach cast {
        DboSchPageToDboPage
        DboSchematicPageToDboPage
        DboPageContentsToDboPage
        DboBaseObjectToDboPage
    } {
        if {[llength [info commands $cast]] != 1} {
            continue
        }
        if {[catch {$cast $pPage} pg]} {
            continue
        }
        if {$pg eq "" || $pg eq $lNullObj} {
            continue
        }
        if {[catch {$pg NewPartInstsIter $lStatus} probe3] != 0} {
            continue
        }
        if {$probe3 ne $lNullObj && $probe3 ne ""} {
            delete_DboPagePartInstsIter $probe3
        }
        return $pg
    }
    return $pPage
}

# 从 PortInst/PartInst 等图形对象向上解析所在原理图名、页名（供 FlatNet 管脚写入与页内聚合键一致）
proc ::capExport::dboSchPageNamesForGraphicalObj {obj lStatus lNullObj} {
    if {$obj eq "" || $obj eq "NULL" || $obj == $lNullObj} {
        return [list "" ""]
    }
    set pgObj [::capExport::drawingPageFrom $obj $lStatus]
    set pgNm ""
    if {$pgObj ne "" && $pgObj ne "NULL" && $pgObj != $lNullObj} {
        set c [DboTclHelper_sMakeCString]
        if {![catch {$pgObj GetName $c}]} {
            set pgNm [string trim [DboTclHelper_sGetConstCharPtr $c]]
        }
    }
    set schNm ""
    if {$pgObj ne "" && $pgObj ne "NULL" && $pgObj != $lNullObj} {
        if {![catch {$pgObj GetOwner} sObj]} {
            if {$sObj ne "" && $sObj ne "NULL" && $sObj != $lNullObj} {
                set c2 [DboTclHelper_sMakeCString]
                if {![catch {$sObj GetName $c2}]} {
                    set schNm [string trim [DboTclHelper_sGetConstCharPtr $c2]]
                }
            }
        }
    }
    return [list $schNm $pgNm]
}

# 导线迭代：17.4 部分页对象无 NewWiresIter，仅有 NewWiresInAreaIter
proc ::capExport::openWireIterator {lPageDb lStatus lNullObj} {
    if {[catch {$lPageDb NewWiresIter $lStatus} it] == 0} {
        if {$it ne $lNullObj && $it ne ""} {
            return $it
        }
    }
    foreach coords {
        {-500000 -500000 2000000 2000000}
        {-2000000 -2000000 6000000 6000000}
    } {
        set x1 [lindex $coords 0]
        set y1 [lindex $coords 1]
        set x2 [lindex $coords 2]
        set y2 [lindex $coords 3]
        if {[catch {$lPageDb NewWiresInAreaIter $lStatus $x1 $y1 $x2 $y2} it2] == 0} {
            if {$it2 ne $lNullObj && $it2 ne ""} {
                return $it2
            }
        }
    }
    if {[llength [info commands DboTclHelper_sMakeCRect]]} {
        set it3 ""
        if {[catch {
            set r [DboTclHelper_sMakeCRect]
            DboTclHelper_sSetCRect $r -500000 -500000 2000000 2000000
            set it3 [$lPageDb NewWiresInAreaIter $lStatus $r]
        }]} {
            set it3 ""
        }
        if {$it3 ne $lNullObj && $it3 ne ""} {
            return $it3
        }
    }
    return ""
}

# 扫描单页：收集所有实例的有效属性名（供宽表列头）
proc ::capExport::_scanPageForPropKeys {pPage pSch pPg lStatus lNullObj} {
    set lPageDb [::capExport::drawingPageFrom $pPage $lStatus]
    if {[catch {set lPartInstIter [$lPageDb NewPartInstsIter $lStatus]}]} {
        return
    }
    set lPartInst [$lPartInstIter NextPartInst $lStatus]
    while {$lPartInst != $lNullObj} {
        set lPlacedInst [DboPartInstToDboPlacedInst $lPartInst]
        if {$lPlacedInst == $lNullObj} {
            set lPlacedInst $lPartInst
        }
        set effList [::capExport::placedInstEffectivePropsList $lPlacedInst $lNullObj $lStatus]
        foreach {k v} $effList {
            if {$k ne ""} {
                set ::capExport::_partWideKeys($k) 1
            }
        }
        set lPartInst [$lPartInstIter NextPartInst $lStatus]
    }
    delete_DboPagePartInstsIter $lPartInstIter
}

proc ::capExport::_scanPagesOfSchematic {lSchematic lStatus lNullObj} {
    if {$lSchematic == $lNullObj} {
        return
    }
    set lSchematicNameStr [DboTclHelper_sMakeCString]
    $lSchematic GetName $lSchematicNameStr
    set lSchematicName [DboTclHelper_sGetConstCharPtr $lSchematicNameStr]
    set lPagesIter [$lSchematic NewPagesIter $lStatus]
    set lPage [$lPagesIter NextPage $lStatus]
    while {$lPage != $lNullObj} {
        set lPageNameStr [DboTclHelper_sMakeCString]
        $lPage GetName $lPageNameStr
        set lPageName [DboTclHelper_sGetConstCharPtr $lPageNameStr]
        ::capExport::_scanPageForPropKeys $lPage $lSchematicName $lPageName $lStatus $lNullObj
        set lPage [$lPagesIter NextPage $lStatus]
    }
    delete_DboSchematicPagesIter $lPagesIter
}

# 宽表动态列不与固定列重名（否则 Excel 里出现两列「PCB Footprint」等，易错列/出现被截断的数值）
proc ::capExport::_partWideKeyExcluded {key} {
    set k [string tolower [string trim $key]]
    foreach x {
        reference designator schematic page value
        {source library} {pcb footprint} {position x} {position y} rotation
    } {
        if {$k eq [string tolower $x]} {
            return 1
        }
    }
    return 0
}

# 全设计扫描：有效属性名的并集 → ::capExport::_partWideKeys
proc ::capExport::collectPartWidePropColumnNames {pDesign lStatus lNullObj} {
    array unset ::capExport::_partWideKeys
    array set ::capExport::_partWideKeys {}
    array set doneSch {}
    set lRoot [$pDesign GetRootSchematic $lStatus]
    if {$lRoot != $lNullObj} {
        set doneSch([format {%s} $lRoot]) 1
        if {[catch {::capExport::_scanPagesOfSchematic $lRoot $lStatus $lNullObj} er]} {
            puts "capExport scan props (root): $er"
        }
    }
    if {![info exists ::IterDefs_SCHEMATICS]} {
        return
    }
    set lSchematicIter [$pDesign NewViewsIter $lStatus $::IterDefs_SCHEMATICS]
    set lView [$lSchematicIter NextView $lStatus]
    while {$lView != $lNullObj} {
        set lSchematic [DboViewToDboSchematic $lView]
        if {$lSchematic == $lNullObj} {
            set lView [$lSchematicIter NextView $lStatus]
            continue
        }
        set schTag [format {%s} $lSchematic]
        if {[info exists doneSch($schTag)]} {
            set lView [$lSchematicIter NextView $lStatus]
            continue
        }
        set doneSch($schTag) 1
        if {[catch {::capExport::_scanPagesOfSchematic $lSchematic $lStatus $lNullObj} es]} {
            puts "capExport scan props: $es"
        }
        set lView [$lSchematicIter NextView $lStatus]
    }
    catch {delete_DboLibViewsIter $lSchematicIter}
    DboTclHelper_sReleaseAllCreatedPtrs
}

# 导出器件属性：每位号一行，首列为位号；仅有效属性（3.2.24），每属性单独一列（宽表）
proc ::capExport::exportPartProperties {pPage fileId {pSch ""} {pPg ""}} {
    set lStatus [DboState]
    set lNullObj NULL
    set lPageDb [::capExport::drawingPageFrom $pPage $lStatus]
    
    if {[catch {set lPartInstIter [$lPageDb NewPartInstsIter $lStatus]} err]} {
        puts "capExport exportPartProperties: skip page (no NewPartInstsIter): $err"
        $lStatus -delete
        return
    }
    set lPartInst [$lPartInstIter NextPartInst $lStatus]
    
    while {$lPartInst != $lNullObj} {
        set lPlacedInst [DboPartInstToDboPlacedInst $lPartInst]
        if {$lPlacedInst == $lNullObj} {
            set lPlacedInst $lPartInst
        }
        
        set lRefDesStr [DboTclHelper_sMakeCString]
        $lPartInst GetReferenceDesignator $lRefDesStr
        set lRefDes [DboTclHelper_sGetConstCharPtr $lRefDesStr]
        
        set lPartValueStr [DboTclHelper_sMakeCString]
        $lPartInst GetPartValue $lPartValueStr
        set lPartValue [DboTclHelper_sGetConstCharPtr $lPartValueStr]
        
        set lSourceLibStr [DboTclHelper_sMakeCString]
        $lPlacedInst GetSourceLibName $lSourceLibStr
        set lSourceLib [DboTclHelper_sGetConstCharPtr $lSourceLibStr]
        
        set lPCBFootprintStr [DboTclHelper_sMakeCString]
        $lPlacedInst GetPCBFootprint $lPCBFootprintStr
        set lPCBFootprint [DboTclHelper_sGetConstCharPtr $lPCBFootprintStr]
        
        set lLocation [$lPlacedInst GetLocation $lStatus]
        set lPosX [DboTclHelper_sGetCPointX $lLocation]
        set lPosY [DboTclHelper_sGetCPointY $lLocation]
        
        set lRotation [$lPlacedInst GetRotation $lStatus]
        
        set effList [::capExport::placedInstEffectivePropsList $lPlacedInst $lNullObj $lStatus]
        set lRefDisp [::capExport::displayRefDesFromEffList $lRefDes $effList]
        set lRefDisp [::capExport::_disambiguateRefDes $lRefDisp $pPg]
        if {[string trim $lRefDisp] eq ""} {
            set lPartInst [$lPartInstIter NextPartInst $lStatus]
            continue
        }
        variable mPartWideColNames
        puts $fileId [::capExport::csvRowPartWide $lRefDisp $pSch $pPg $lPartValue $lSourceLib $lPCBFootprint $lPosX $lPosY $lRotation $effList $mPartWideColNames]
        
        set lPartInst [$lPartInstIter NextPartInst $lStatus]
    }
    
    delete_DboPagePartInstsIter $lPartInstIter
    $lStatus -delete
}

# SPB17.4：无 NewNetsIter 时按导线导出；每根线段一行，便于统计与分列
proc ::capExport::exportNetInfoFromWires {pPageRaw lPageDb fileId lStatus lNullObj schName pageName} {
    set lWiresIter [::capExport::openWireIterator $lPageDb $lStatus $lNullObj]
    if {$lWiresIter eq ""} {
        set lWiresIter [::capExport::openWireIterator $pPageRaw $lStatus $lNullObj]
    }
    if {$lWiresIter eq ""} {
        puts "capExport exportNetInfo: no wire iterator on page"
        return
    }
    set lWire [$lWiresIter NextWire $lStatus]
    while {$lWire != $lNullObj} {
        set lNetName ""
        if {[catch {
            set lWireNet [$lWire GetNet $lStatus]
            if {$lWireNet ne $lNullObj && $lWireNet ne ""} {
                set lNetName [::capExport::dboObjectNameStr $lWireNet]
            }
            if {$lNetName eq ""} {
                set lNetName [::capExport::dboObjectNameStr $lWire]
            }
        }]} {
            set lWire [$lWiresIter NextWire $lStatus]
            continue
        }
        set lbl [::capExport::_netsRowLabelFromNetObjs $schName $pageName $lNetName $lStatus $lNullObj $lWireNet]
        if {[string trim $lbl] eq ""} {
            set lWire [$lWiresIter NextWire $lStatus]
            continue
        }
        set pinPage [::capExport::_aggNetPinJoinStr $schName $pageName $lbl]
        set pinGlobal [::capExport::_aggGlobalNetPinJoinStr $lbl]
        ::capExport::_netsEmitRowIfNew $fileId $lbl $schName $pageName $pinPage $pinGlobal
        set lWire [$lWiresIter NextWire $lStatus]
    }
    catch {delete_DboPageWiresIter $lWiresIter}
}

# 导出网络信息（同一页同一网名一行；可选原理图/页名）
proc ::capExport::exportNetInfo {pPage fileId {pSch ""} {pPg ""}} {
    set lStatus [DboState]
    set lNullObj NULL
    catch {array unset ::capExport::_netCsvRowEmitted}
    array set ::capExport::_netCsvRowEmitted {}
    set lPageDb [::capExport::drawingPageFrom $pPage $lStatus]
    
    set lNetsIter ""
    set lHaveNetsIter 0
    if {[catch {set lNetsIter [$lPageDb NewNetsIter $lStatus]} err] == 0} {
        if {$lNetsIter ne $lNullObj && $lNetsIter ne ""} {
            set lHaveNetsIter 1
        }
    }
    
    if {!$lHaveNetsIter} {
        ::capExport::exportNetInfoFromWires $pPage $lPageDb $fileId $lStatus $lNullObj $pSch $pPg
        $lStatus -delete
        return
    }
    
    set lNet [$lNetsIter NextNet $lStatus]
    while {$lNet != $lNullObj} {
        set lNetNameLocal [::capExport::dboObjectNameStr $lNet]
        
        set lWiresIter [::capExport::openWireIterator $lPageDb $lStatus $lNullObj]
        if {$lWiresIter eq ""} {
            set lWiresIter [::capExport::openWireIterator $pPage $lStatus $lNullObj]
        }
        if {$lWiresIter ne ""} {
            set lWire [$lWiresIter NextWire $lStatus]
            while {$lWire != $lNullObj} {
                if {[catch {
                    set lWireNet [$lWire GetNet $lStatus]
                    if {[::capExport::_wireNetSameAs $lWireNet $lNet $lNetNameLocal $lStatus $lNullObj]} {
                        set lbl [::capExport::_netsRowLabelFromNetObjs $pSch $pPg $lNetNameLocal $lStatus $lNullObj $lNet $lWireNet]
                        if {[string trim $lbl] ne ""} {
                            set pinPage [::capExport::_aggNetPinJoinStr $pSch $pPg $lbl]
                            set pinGlobal [::capExport::_aggGlobalNetPinJoinStr $lbl]
                            ::capExport::_netsEmitRowIfNew $fileId $lbl $pSch $pPg $pinPage $pinGlobal
                        }
                    }
                }]} {}
                set lWire [$lWiresIter NextWire $lStatus]
            }
            catch {delete_DboPageWiresIter $lWiresIter}
        } else {
            set lbl [::capExport::_netsRowLabelFromNetObjs $pSch $pPg $lNetNameLocal $lStatus $lNullObj $lNet]
            if {[string trim $lbl] ne ""} {
                set pinPage [::capExport::_aggNetPinJoinStr $pSch $pPg $lbl]
                set pinGlobal [::capExport::_aggGlobalNetPinJoinStr $lbl]
                ::capExport::_netsEmitRowIfNew $fileId $lbl $pSch $pPg $pinPage $pinGlobal
            }
        }
        
        set lNet [$lNetsIter NextNet $lStatus]
    }
    
    delete_DboPageNetsIter $lNetsIter
    $lStatus -delete
}

# 单行管脚 CSV：Reference, Pin Number, Pin Name, Net Name, Schematic, Page
proc ::capExport::csvRowPinRecord {ref pnum pnm netNm sch pg} {
    return [::capExport::csvRow [list $ref $pnum $pnm $netNm $sch $pg]]
}

# 从 PortInst/管脚对象取网络名（多签名 GetNet；后续 dbo 可能非 Net，须整体 catch 避免 Invalid method 中断整页）
proc ::capExport::pinGetNetName {lp lStatus lNullObj} {
    set netNm ""
    if {[catch {
        set ln $lNullObj
        if {![catch {set ln [$lp GetNet $lStatus]}]} {
        } elseif {![catch {set ln [$lp GetNet]}]} {
        } elseif {![catch {$lp GetNet ln}]} {
        }
        if {$ln ne $lNullObj && $ln ne "" && $ln ne "NULL"} {
            set netNm [::capExport::dboObjectNameStr $ln]
        }
    }]} {
        return ""
    }
    return $netNm
}

# 管脚聚合键：优先从管脚所连标量网 GetFlatNet（与 Capture「Net Name」一致），避免 OffPage/别名在聚合里拆成多网
proc ::capExport::pinAggKeyFromPin {lp pSch pPg lStatus lNullObj} {
    set netNm [::capExport::pinGetNetName $lp $lStatus $lNullObj]
    set ln $lNullObj
    if {[catch {
        if {![catch {set ln [$lp GetNet $lStatus]}]} {
        } elseif {![catch {set ln [$lp GetNet]}]} {
        } elseif {![catch {$lp GetNet ln}]} {
        }
    }]} {
        set ln $lNullObj
    }
    if {$ln ne $lNullObj && $ln ne "" && $ln ne "NULL"} {
        set fo [::capExport::flatNetNameFromScalarNet $ln $lStatus $lNullObj]
        if {$fo ne ""} {
            set loc [string trim $netNm]
            if {$loc ne "" && $loc ne $fo} {
                ::capExport::_flatMapSetAlias $pSch $pPg $loc $fo
            }
            return $fo
        }
    }
    return [::capExport::_netAggKeyName $pSch $pPg $netNm]
}

# FlatNet 端口上 pinGetNetName 常为空：从 PortOccurrence/PortInst 再试取页内逻辑网名（供别名映射）
proc ::capExport::portOccLocalNetName {po pinst lStatus lNullObj} {
    foreach obj [list $po $pinst] {
        if {$obj eq "" || $obj eq "NULL" || $obj == $lNullObj} {
            continue
        }
        set t [::capExport::pinGetNetName $obj $lStatus $lNullObj]
        if {[string trim $t] ne ""} {
            return $t
        }
    }
    foreach obj [list $pinst $po] {
        if {$obj eq "" || $obj eq "NULL" || $obj == $lNullObj} {
            continue
        }
        foreach m {GetLogicalNetName GetNetName} {
            set t [::capExport::dboObjOneString $obj $m]
            if {[string trim $t] ne ""} {
                return $t
            }
        }
    }
    return ""
}

# 页内标量网对象 → FlatNet 名（若 API 可用，补全端口映射未覆盖的别名）
proc ::capExport::flatNetNameFromScalarNet {netObj lStatus lNullObj} {
    if {$netObj eq "" || $netObj eq "NULL" || $netObj == $lNullObj} {
        return ""
    }
    set fnet $lNullObj
    if {![catch {set fnet [$netObj GetFlatNet $lStatus]}]} {
    } elseif {![catch {set fnet [$netObj GetFlatNet]}]} {
    } elseif {![catch {$netObj GetFlatNet fnet}]} {
    }
    if {$fnet ne "" && $fnet ne "NULL" && $fnet != $lNullObj} {
        return [string trim [::capExport::dboObjectNameStr $fnet]]
    }
    return ""
}

proc ::capExport::_flatMapSetAlias {sch pg localNm flatNm} {
    set loc [string trim $localNm]
    set flat [string trim $flatNm]
    if {$loc eq "" || $flat eq ""} {
        return
    }
    set k [::capExport::_aggNetPinKey $sch $pg $loc]
    set ::capExport::_localNetFlatName($k) $flat
    set k0 [::capExport::_aggNetPinKey "" "" $loc]
    if {$k0 ne $k} {
        if {![info exists ::capExport::_localNetFlatName($k0)]} {
            set ::capExport::_localNetFlatName($k0) $flat
        }
    }
}

proc ::capExport::_scanPageWiresForFlatAliases {pPageRaw lPageDb pSch pPg lStatus lNullObj} {
    set lWiresIter [::capExport::openWireIterator $lPageDb $lStatus $lNullObj]
    if {$lWiresIter eq ""} {
        set lWiresIter [::capExport::openWireIterator $pPageRaw $lStatus $lNullObj]
    }
    if {$lWiresIter eq ""} {
        return
    }
    set lWire [$lWiresIter NextWire $lStatus]
    while {$lWire != $lNullObj} {
        if {![catch {
            set lWireNet [$lWire GetNet $lStatus]
            if {$lWireNet eq $lNullObj || $lWireNet eq ""} {
                set lWire [$lWiresIter NextWire $lStatus]
                continue
            }
            set loc [string trim [::capExport::dboObjectNameStr $lWireNet]]
            if {$loc eq ""} {
                set loc [string trim [::capExport::dboObjectNameStr $lWire]]
            }
            if {$loc ne ""} {
                set flat [::capExport::flatNetNameFromScalarNet $lWireNet $lStatus $lNullObj]
                if {$flat ne ""} {
                    ::capExport::_flatMapSetAlias $pSch $pPg $loc $flat
                }
            }
        }]} {}
        set lWire [$lWiresIter NextWire $lStatus]
    }
    catch {delete_DboPageWiresIter $lWiresIter}
}

proc ::capExport::_scanPageNetsForFlatAliases {pPage pSch pPg lStatus lNullObj} {
    set lPageDb [::capExport::drawingPageFrom $pPage $lStatus]
    set lNetsIter ""
    set lHaveNetsIter 0
    if {[catch {set lNetsIter [$lPageDb NewNetsIter $lStatus]} err] == 0} {
        if {$lNetsIter ne $lNullObj && $lNetsIter ne ""} {
            set lHaveNetsIter 1
        }
    }
    if {!$lHaveNetsIter} {
        ::capExport::_scanPageWiresForFlatAliases $pPage $lPageDb $pSch $pPg $lStatus $lNullObj
        return
    }
    set lNet [$lNetsIter NextNet $lStatus]
    while {$lNet != $lNullObj} {
        set loc [string trim [::capExport::dboObjectNameStr $lNet]]
        if {$loc ne ""} {
            set flat [::capExport::flatNetNameFromScalarNet $lNet $lStatus $lNullObj]
            if {$flat ne ""} {
                ::capExport::_flatMapSetAlias $pSch $pPg $loc $flat
            }
        }
        set lNet [$lNetsIter NextNet $lStatus]
    }
    catch {delete_DboPageNetsIter $lNetsIter}
}

proc ::capExport::_scanPagesOfSchematicForFlatMap {lSchematic lStatus lNullObj} {
    if {$lSchematic == $lNullObj} {
        return
    }
    set lSchematicNameStr [DboTclHelper_sMakeCString]
    $lSchematic GetName $lSchematicNameStr
    set lSchematicName [DboTclHelper_sGetConstCharPtr $lSchematicNameStr]
    set lPagesIter [$lSchematic NewPagesIter $lStatus]
    set lPage [$lPagesIter NextPage $lStatus]
    while {$lPage != $lNullObj} {
        set lPageNameStr [DboTclHelper_sMakeCString]
        $lPage GetName $lPageNameStr
        set lPageName [DboTclHelper_sGetConstCharPtr $lPageNameStr]
        if {[catch {::capExport::_scanPageNetsForFlatAliases $lPage $lSchematicName $lPageName $lStatus $lNullObj} ef]} {
            puts "capExport scan page nets for flat map ($lSchematicName / $lPageName): $ef"
        }
        set lPage [$lPagesIter NextPage $lStatus]
    }
    delete_DboSchematicPagesIter $lPagesIter
}

# 全设计页内标量网 → FlatNet 别名补充（在 Flat 端口映射之后调用）
proc ::capExport::extendFlatMapFromAllSchematics {pDesign lStatus lNullObj} {
    if {[catch {
        array set doneSch {}
        set lRoot [$pDesign GetRootSchematic $lStatus]
        if {$lRoot != $lNullObj} {
            set doneSch([format {%s} $lRoot]) 1
            ::capExport::_scanPagesOfSchematicForFlatMap $lRoot $lStatus $lNullObj
        }
        if {![info exists ::IterDefs_SCHEMATICS]} {
            return
        }
        set lSchematicIter [$pDesign NewViewsIter $lStatus $::IterDefs_SCHEMATICS]
        set lView [$lSchematicIter NextView $lStatus]
        while {$lView != $lNullObj} {
            set lSchematic [DboViewToDboSchematic $lView]
            if {$lSchematic == $lNullObj} {
                set lView [$lSchematicIter NextView $lStatus]
                continue
            }
            set schTag [format {%s} $lSchematic]
            if {[info exists doneSch($schTag)]} {
                set lView [$lSchematicIter NextView $lStatus]
                continue
            }
            set doneSch($schTag) 1
            if {[catch {::capExport::_scanPagesOfSchematicForFlatMap $lSchematic $lStatus $lNullObj} es]} {
                puts "capExport extendFlatMap schematic $schTag: $es"
            }
            set lView [$lSchematicIter NextView $lStatus]
        }
        catch {delete_DboLibViewsIter $lSchematicIter}
        DboTclHelper_sReleaseAllCreatedPtrs
    } err]} {
        puts "capExport extendFlatMapFromAllSchematics: $err"
    }
}

# 对 $pinParent 打开 NewPinsIter（层次块优先用 DboDrawnInst）
proc ::capExport::_openPinsIterOnInst {lPartInst lPlacedInst lNullObj lStatus} {
    set pinParent $lPlacedInst
    if {[catch {set lDrawn [DboPartInstToDboDrawnInst $lPartInst]}] == 0} {
        if {$lDrawn != $lNullObj && $lDrawn ne ""} {
            set pinParent $lDrawn
        }
    }
    set lInstPinsIt ""
    if {[catch {set lInstPinsIt [$pinParent NewPinsIter $lStatus]}]} {
        set lInstPinsIt ""
    }
    if {($lInstPinsIt eq $lNullObj || $lInstPinsIt eq "") && $pinParent ne $lPartInst} {
        if {![catch {set lInstPinsIt [$lPartInst NewPinsIter $lStatus]}]} {
            if {$lInstPinsIt eq $lNullObj} {
                set lInstPinsIt ""
            }
        }
    }
    if {($lInstPinsIt eq $lNullObj || $lInstPinsIt eq "") && $pinParent ne $lPlacedInst} {
        if {![catch {set lInstPinsIt [$lPlacedInst NewPinsIter $lStatus]}]} {
            if {$lInstPinsIt eq $lNullObj} {
                set lInstPinsIt ""
            }
        }
    }
    return [list $lInstPinsIt $pinParent]
}

# 导出管脚信息（优先实例管脚含网络；写入 Pins_Info，并记入按网聚合供 Nets_Info）
proc ::capExport::exportPinInfo {pPage fileId {pSch ""} {pPg ""}} {
    set lStatus [DboState]
    set lNullObj NULL
    set lPageDb [::capExport::drawingPageFrom $pPage $lStatus]
    
    # 获取页面中的所有器件实例
    if {[catch {set lPartInstIter [$lPageDb NewPartInstsIter $lStatus]} err]} {
        puts "capExport exportPinInfo: skip page (no NewPartInstsIter): $err"
        $lStatus -delete
        return
    }
    set lPartInst [$lPartInstIter NextPartInst $lStatus]
    
    while {$lPartInst != $lNullObj} {
        if {[catch {
        set lPlacedInst [DboPartInstToDboPlacedInst $lPartInst]
        if {$lPlacedInst == $lNullObj} {
            set lPlacedInst $lPartInst
        }
        
        # 获取器件参考标识符（基类句柄）
        set lRefDesStr [DboTclHelper_sMakeCString]
        $lPartInst GetReferenceDesignator $lRefDesStr
        set lRefDes [DboTclHelper_sGetConstCharPtr $lRefDesStr]
        set _effPin {}
        if {[catch {set _effPin [::capExport::placedInstEffectivePropsList $lPlacedInst $lNullObj $lStatus]} _eE]} {
            puts "capExport exportPinInfo effProps: $_eE"
        }
        # 不在此调用 _disambiguateRefDes：同页会先跑 Parts 已占用计数，会导致管脚位号误加 @页名
        set lRefDisp [::capExport::displayRefDesFromEffList $lRefDes $_effPin]
        if {[string trim $lRefDisp] eq ""} {
            set lRefDisp [string trim $lRefDes]
        }
        if {[string trim $lRefDisp] eq ""} {
            set lRefDisp "?"
        }
        
        set _pinOpen [::capExport::_openPinsIterOnInst $lPartInst $lPlacedInst $lNullObj $lStatus]
        set lInstPinsIt [lindex $_pinOpen 0]
        set pinParent [lindex $_pinOpen 1]
        # 实例管脚已含原理图网络；若已写出至少一行则不再遍历库符号管脚，避免同一料号出现 2+2 等重复行（如双端电容变 4 行）
        # 勿按「网名」去重：多脚 IC（如 U1000）常有多脚接同一 GND/VCC，按网去重会大量丢脚。
        set _instPinRowsWritten 0
        catch {array unset _seenInstPinKey}
        array set _seenInstPinKey {}
        if {$lInstPinsIt ne $lNullObj && $lInstPinsIt ne ""} {
            set lp [$lInstPinsIt NextPin $lStatus]
            while {$lp != $lNullObj} {
                if {[catch {
                    set cs [DboTclHelper_sMakeCString]
                    if {[catch {$lp GetPinNumber $cs}]} {
                        if {[catch {$lp GetPinName $cs}]} {
                            catch {$lp GetDesignator $cs}
                        }
                    }
                    set pnum [DboTclHelper_sGetConstCharPtr $cs]
                    set cs2 [DboTclHelper_sMakeCString]
                    if {[catch {$lp GetPinName $cs2}]} {
                        catch {$lp GetDesignator $cs2}
                    }
                    set pnm [DboTclHelper_sGetConstCharPtr $cs2]
                    set netNm [::capExport::pinGetNetName $lp $lStatus $lNullObj]
                    set pit [string trim $pnum]
                    set pmt [string trim $pnm]
                    set pk ""
                    if {$pit ne ""} {
                        set pk "n\t$pit"
                    } elseif {$pmt ne ""} {
                        set pk "m\t$pmt"
                    }
                    if {$pk ne "" && [info exists _seenInstPinKey($pk)]} {
                    } else {
                        if {$pk ne ""} {
                            set _seenInstPinKey($pk) 1
                        }
                        set netFlat [::capExport::pinAggKeyFromPin $lp $pSch $pPg $lStatus $lNullObj]
                        ::capExport::_aggNetPinAdd $pSch $pPg $netFlat $lRefDisp $pnum
                        puts $fileId [::capExport::csvRowPinRecord $lRefDisp $pnum $pnm $netNm $pSch $pPg]
                        incr _instPinRowsWritten
                    }
                }]} {}
                set lp [$lInstPinsIt NextPin $lStatus]
            }
            catch {delete_DboPinsIter $lInstPinsIt}
            catch {delete_DboPlacedInstPinsIter $lInstPinsIt}
            catch {delete_DboPartInstPinsIter $lInstPinsIt}
        }
        
        # 获取器件包（部分实例无包或非 Placed 语义，避免抛错中断整颗料）
        set lCachedPackage $lNullObj
        catch {set lCachedPackage [$lPlacedInst GetPackage $lStatus]}
        
        if {$lCachedPackage != $lNullObj && $_instPinRowsWritten == 0} {
            # 获取包中的所有器件
            set lDevicesIter [$lCachedPackage NewDevicesIter $lStatus]
            set lDevice [$lDevicesIter NextDevice $lStatus]
            
            while {$lDevice != $lNullObj} {
                # 获取器件中的所有单元
                set lCellsIter [$lDevice NewCellsIter $lStatus]
                set lCell [$lCellsIter NextCell $lStatus]
                
                while {$lCell != $lNullObj} {
                    # 获取单元中的所有符号引脚
                    set lPinsIter [$lCell NewSymbolPinsIter $lStatus]
                    set lPin [$lPinsIter NextSymbolPin $lStatus]
                    
                    while {$lPin != $lNullObj} {
                        if {[catch {
                            # SPB17.4 符号管脚常无 GetName，仅有 GetDesignator / GetPinNumber / GetCellName 等
                            set lPinNameStr [DboTclHelper_sMakeCString]
                            if {[catch {$lPin GetDesignator $lPinNameStr}]} {
                                if {[catch {$lPin GetPinNumber $lPinNameStr}]} {
                                    if {[catch {$lPin GetCellName $lPinNameStr}]} {
                                        catch {$lPin GetName $lPinNameStr}
                                    }
                                }
                            }
                            set lPinName [DboTclHelper_sGetConstCharPtr $lPinNameStr]
                            set lPinNumberStr [DboTclHelper_sMakeCString]
                            if {[catch {$lPin GetPinNumber $lPinNumberStr}]} {
                                if {[catch {$lPin GetDesignator $lPinNumberStr}]} {
                                    catch {$lPin GetCellName $lPinNumberStr}
                                }
                            }
                            set lPinNumber [DboTclHelper_sGetConstCharPtr $lPinNumberStr]
                            set netNm [::capExport::pinGetNetName $lPin $lStatus $lNullObj]
                            set netFlat [::capExport::pinAggKeyFromPin $lPin $pSch $pPg $lStatus $lNullObj]
                            ::capExport::_aggNetPinAdd $pSch $pPg $netFlat $lRefDisp $lPinNumber
                            puts $fileId [::capExport::csvRowPinRecord $lRefDisp $lPinNumber $lPinName $netNm $pSch $pPg]
                        }]} {
                            # 非电气管脚等对象 API 不一致时跳过
                        }
                        set lPin [$lPinsIter NextSymbolPin $lStatus]
                    }
                    catch {delete_DboCellSymbolPinsIter $lPinsIter}
                    
                    set lCell [$lCellsIter NextCell $lStatus]
                }
                catch {delete_DboDeviceCellsIter $lCellsIter}
                
                set lDevice [$lDevicesIter NextDevice $lStatus]
            }
            catch {delete_DboPackageDevicesIter $lDevicesIter}
        }
        } _partPinErr]} {
            puts "capExport exportPinInfo part: $_partPinErr"
        }
        set lPartInst [$lPartInstIter NextPartInst $lStatus]
    }
    
    delete_DboPagePartInstsIter $lPartInstIter
    $lStatus -delete
}

# 遍历单个原理图下的所有页面：pinsOnly=1 仅收集管脚/Pins_Info；pinsOnly=0 导出器件与网络（Nets 需先有管脚聚合）
proc ::capExport::_exportPagesOfSchematic {lSchematic partsFileId netsFileId pinsFileId lStatus lNullObj pinsOnly} {
    if {$lSchematic == $lNullObj} {
        return
    }
    set lSchematicNameStr [DboTclHelper_sMakeCString]
    $lSchematic GetName $lSchematicNameStr
    set lSchematicName [DboTclHelper_sGetConstCharPtr $lSchematicNameStr]
    
    set lPagesIter [$lSchematic NewPagesIter $lStatus]
    set lPage [$lPagesIter NextPage $lStatus]
    while {$lPage != $lNullObj} {
        set lPageNameStr [DboTclHelper_sMakeCString]
        $lPage GetName $lPageNameStr
        set lPageName [DboTclHelper_sGetConstCharPtr $lPageNameStr]
        
        if {$pinsOnly} {
            if {[catch {::capExport::exportPinInfo $lPage $pinsFileId $lSchematicName $lPageName} eI]} {
                puts "capExport Pins (page $lPageName): $eI"
            }
            catch {flush $pinsFileId}
        } else {
            if {[catch {::capExport::exportPartProperties $lPage $partsFileId $lSchematicName $lPageName} eP]} {
                puts "capExport Parts (page $lPageName): $eP"
            }
            if {[catch {::capExport::exportNetInfo $lPage $netsFileId $lSchematicName $lPageName} eN]} {
                puts "capExport Nets (page $lPageName): $eN"
            }
            catch {flush $partsFileId}
            catch {flush $netsFileId}
        }
        
        set lPage [$lPagesIter NextPage $lStatus]
    }
    delete_DboSchematicPagesIter $lPagesIter
    # 勿在 exportPart/exportNet/exportPin 每页末尾调用 ReleaseAllCreatedPtrs：会释放父级仍持有的页迭代器包装，NextPage 提前结束，Pins/Parts 仅前几页有数据
    DboTclHelper_sReleaseAllCreatedPtrs
}

# 遍历所有原理图页面
proc ::capExport::visitSchematics {pDesign} {
    set lStatus [DboState]
    set lNullObj NULL
    set partsFileId ""
    set netsFileId ""
    set pinsFileId ""
    set flatDesignFileId ""
    set lSchematicIter ""
    set innerMsg ""
    set innerErr 0
    
    if {[catch {
        ::capExport::collectPartWidePropColumnNames $pDesign $lStatus $lNullObj
        set wideKeys {}
        foreach w [lsort [array names ::capExport::_partWideKeys]] {
            if {![::capExport::_partWideKeyExcluded $w]} {
                lappend wideKeys $w
            }
        }
        set ::capExport::mPartWideColNames $wideKeys
        if {![info exists ::IterDefs_SCHEMATICS]} {
            error "IterDefs_SCHEMATICS is not defined (run inside OrCAD Capture Tcl; see doc 3.2.7)"
        }
        set partsHdrList [list "Reference Designator" Schematic Page Value "Source Library" "PCB Footprint" "Position X" "Position Y" Rotation]
        set partsHdrList [concat $partsHdrList $wideKeys]
        set partsHeaderLine [::capExport::csvRow $partsHdrList]
        set partsFileId [::capExport::createCSVFile "Parts_Properties.csv" $partsHeaderLine]
        set netsHdr [::capExport::csvRow [list FlatNet Schematic Page {Pins (Page)} {Pins (Global)}]]
        set netsFileId [::capExport::createCSVFile "Nets_Info.csv" $netsHdr]
        set pinsHdr [::capExport::csvRow [list Reference {Pin Number} {Pin Name} {Net Name} Schematic Page]]
        set pinsFileId [::capExport::createCSVFile "Pins_Info.csv" $pinsHdr]
        catch {array unset ::capExport::_aggNetPins}
        array set ::capExport::_aggNetPins {}
        catch {array unset ::capExport::_aggGlobalNetPins}
        array set ::capExport::_aggGlobalNetPins {}
        ::capExport::buildLocalNetToFlatMap $pDesign $lStatus $lNullObj
        ::capExport::extendFlatMapFromAllSchematics $pDesign $lStatus $lNullObj
        ::capExport::_logInfo "capExport: after page-extend, alias-map keys [array size ::capExport::_localNetFlatName]"
        
        array set doneSch {}
        
        set lRoot [$pDesign GetRootSchematic $lStatus]
        if {$lRoot != $lNullObj} {
            set doneSch([format {%s} $lRoot]) 1
            if {[catch {
                ::capExport::_exportPagesOfSchematic $lRoot "" "" $pinsFileId $lStatus $lNullObj 1
            } eroot]} {
                puts "capExport root schematic (pins pass): $eroot"
            }
        }
        
        set lSchematicIter [$pDesign NewViewsIter $lStatus $::IterDefs_SCHEMATICS]
        set lView [$lSchematicIter NextView $lStatus]
        
        while {$lView != $lNullObj} {
            set lSchematic [DboViewToDboSchematic $lView]
            if {$lSchematic == $lNullObj} {
                set lView [$lSchematicIter NextView $lStatus]
                continue
            }
            set schTag [format {%s} $lSchematic]
            if {[info exists doneSch($schTag)]} {
                set lView [$lSchematicIter NextView $lStatus]
                continue
            }
            set doneSch($schTag) 1
            if {[catch {
                ::capExport::_exportPagesOfSchematic $lSchematic "" "" $pinsFileId $lStatus $lNullObj 1
            } esc]} {
                puts "capExport schematic $schTag (pins pass): $esc"
            }
            set lView [$lSchematicIter NextView $lStatus]
        }
        
        if {[catch {::capExport::appendFlatNetPinRows $pDesign $pinsFileId $lStatus $lNullObj} ef]} {
            puts "capExport appendFlatNetPinRows: $ef"
        }
        catch {flush $pinsFileId}
        
        if {$lRoot != $lNullObj} {
            if {[catch {
                ::capExport::_exportPagesOfSchematic $lRoot $partsFileId $netsFileId "" $lStatus $lNullObj 0
            } eroot2]} {
                puts "capExport root schematic (parts/nets): $eroot2"
            }
        }
        set lSchematicIter2 [$pDesign NewViewsIter $lStatus $::IterDefs_SCHEMATICS]
        set lView2 [$lSchematicIter2 NextView $lStatus]
        while {$lView2 != $lNullObj} {
            set lSchematic2 [DboViewToDboSchematic $lView2]
            if {$lSchematic2 == $lNullObj} {
                set lView2 [$lSchematicIter2 NextView $lStatus]
                continue
            }
            set schTag2 [format {%s} $lSchematic2]
            if {$lRoot != $lNullObj && [string equal $schTag2 [format {%s} $lRoot]]} {
                set lView2 [$lSchematicIter2 NextView $lStatus]
                continue
            }
            if {[catch {
                ::capExport::_exportPagesOfSchematic $lSchematic2 $partsFileId $netsFileId "" $lStatus $lNullObj 0
            } esc2]} {
                puts "capExport schematic $schTag2 (parts/nets): $esc2"
            }
            set lView2 [$lSchematicIter2 NextView $lStatus]
        }
        catch {delete_DboLibViewsIter $lSchematicIter2}
        
        if {[catch {
            set flatDesignFileId [::capExport::createCSVFile "FlatNets_Design.csv" [::capExport::csvRow [list FlatNet {Pins (Global)}]]]
            foreach fn [lsort [array names ::capExport::_officialFlatNet]] {
                puts $flatDesignFileId [::capExport::csvRow [list $fn [::capExport::_aggGlobalNetPinJoinStr $fn]]]
            }
            catch {flush $flatDesignFileId}
        } eFlat]} {
            puts "capExport FlatNets_Design.csv: $eFlat"
        }
        
        if {$lSchematicIter ne ""} {
            catch {delete_DboLibViewsIter $lSchematicIter}
            set lSchematicIter ""
        }
    } innerMsg]} {
        set innerErr 1
        puts "capExport visitSchematics: $innerMsg"
    }
    
    if {$lSchematicIter ne ""} {
        catch {delete_DboLibViewsIter $lSchematicIter}
    }
    
    ::capExport::closeCSVFile $partsFileId
    ::capExport::closeCSVFile $netsFileId
    ::capExport::closeCSVFile $pinsFileId
    ::capExport::closeCSVFile $flatDesignFileId
    catch {array unset ::capExport::_aggNetPins}
    catch {array unset ::capExport::_aggGlobalNetPins}
    catch {array unset ::capExport::_localNetFlatName}
    catch {array unset ::capExport::_officialFlatNet}
    catch {array unset ::capExport::_netCsvRowEmitted}
    
    DboTclHelper_sReleaseAllCreatedPtrs
    $lStatus -delete
    
    if {$innerErr} {
        error $innerMsg
    }
}

# 主导出函数
proc ::capExport::exportAllInfo {pDesignPath pOutputPath} {
    # 输出目录规范化（避免相对路径写到 Capture 当前工作目录以外或找不到）
    set pOutputPath [file normalize $pOutputPath]
    set ::capExport::mExportPath $pOutputPath
    
    # 创建输出目录（如果不存在）
    if {![file exists $pOutputPath]} {
        file mkdir $pOutputPath
    }
    unset -nocomplain ::capExport::_effDel
    catch {array unset ::capExport::_refExportSeen}
    catch {array unset ::capExport::_partWideKeys}
    catch {array unset ::capExport::_aggNetPins}
    catch {array unset ::capExport::_aggGlobalNetPins}
    catch {array unset ::capExport::_localNetFlatName}
    catch {array unset ::capExport::_officialFlatNet}
    
    ::capExport::_logInfo "capExport: starting CSV export..."
    
    # 3.2.3 / 3.2.4：新建会话并用实例方法打开设计（文档示例；caprev.tcl 亦提供 DboSession_* 过程式封装）
    set lSession [DboTclHelper_sCreateSession]
    if {[llength [info commands DboSession]]} {
        catch {DboSession -this $lSession}
    }
    set lStatus [DboState]
    set lDesignPath [DboTclHelper_sMakeCString $pDesignPath]
    set lDesign [$lSession GetDesignAndSchematics $lDesignPath $lStatus]
    
    set lNullObj NULL
    if {$lDesign == $lNullObj || $lDesign eq "NULL"} {
        set lError [DboTclHelper_sMakeCString [concat "capExport: design file not found: " $pDesignPath]]
        DboState_WriteToSessionLog $lError
        puts [DboTclHelper_sGetConstCharPtr $lError]
        ::capExport::_deleteCreatedSession $lSession
        $lStatus -delete
        DboTclHelper_sReleaseAllCreatedPtrs
        # 使 capture 子进程非零退出，便于 SchCompare 识别「未导出」而非静默无 CSV
        error "capExport: design file not found or could not open: $pDesignPath"
    }
    
    # 获取设计名称
    set lDesignNameStr [DboTclHelper_sMakeCString]
    $lDesign GetName $lDesignNameStr
    set lDesignName [DboTclHelper_sGetConstCharPtr $lDesignNameStr]
    
    ::capExport::_logInfo "capExport: exporting design: $lDesignName"
    
    # 执行导出（失败时 visitSchematics 仍会关闭 CSV，此处继续释放设计会话）
    set exportOk 1
    set exportErr ""
    if {[catch {::capExport::visitSchematics $lDesign} exportErr]} {
        set exportOk 0
        puts "capExport exportAllInfo: $exportErr"
    }
    
    ::capExport::_removeDesignFromSession $lSession $lDesign
    ::capExport::_deleteCreatedSession $lSession
    $lStatus -delete
    DboTclHelper_sReleaseAllCreatedPtrs
    
    if {!$exportOk} {
        set lMessage "capExport: finished with errors (see console). Output: $pOutputPath"
        set lMessageStr [DboTclHelper_sMakeCString $lMessage]
        catch {DboState_WriteToSessionLog $lMessageStr}
        puts [DboTclHelper_sGetConstCharPtr $lMessageStr]
    } elseif {$::capExport::exportVerbose} {
        ::capExport::_logInfo "capExport: success. Output: $pOutputPath"
        ::capExport::_logInfo "capExport: output files:"
        ::capExport::_logInfo "1. Parts_Properties.csv - part properties (wide table, one row per refdes)"
        ::capExport::_logInfo "2. Nets_Info.csv - nets"
        ::capExport::_logInfo "3. Pins_Info.csv - pins"
        ::capExport::_logInfo "4. FlatNets_Design.csv - one row per design FlatNet (align with Capture FlatNet count)"
    }
}

# 导出当前活动设计
proc ::capExport::exportActiveDesign {pOutputPath} {
    set lSession [::capExport::_captureSession]
    if {$lSession eq ""} {
        set lError [DboTclHelper_sMakeCString "capExport: cannot get Capture session (run from Capture Tcl console; see doc 3.2.2)"]
        catch {DboState_WriteToSessionLog $lError}
        puts [DboTclHelper_sGetConstCharPtr $lError]
        return
    }
    if {[llength [info commands DboSession]]} {
        catch {DboSession -this $lSession}
    }
    
    set lStatus [DboState]
    set lNullObj NULL
    
    # 与当前原理图窗口一致的活动设计；GetName 一般为已保存设计的完整路径
    set lDesign [$lSession GetActiveDesign]
    
    if {$lDesign == $lNullObj} {
        set lError [DboTclHelper_sMakeCString "capExport: no active design is open"]
        DboState_WriteToSessionLog $lError
        puts [DboTclHelper_sGetConstCharPtr $lError]
        $lStatus -delete
        DboTclHelper_sReleaseAllCreatedPtrs
        return
    }
    
    set lDesignNameStr [DboTclHelper_sMakeCString]
    $lDesign GetName $lDesignNameStr
    set lDesignName [DboTclHelper_sGetConstCharPtr $lDesignNameStr]
    
    DboTclHelper_sReleaseAllCreatedPtrs
    $lStatus -delete
    
    # 调用主导出函数（传入 GetName 路径，勿用 pwd 拼接 .dsn）
    ::capExport::exportAllInfo $lDesignName $pOutputPath
}

# 全局简短命令（勿用 interp alias：source 会回显别名名）；用法: exportDsnCsv <.dsn> <输出目录>
proc exportDsnCsv args {
    uplevel #0 [linsert $args 0 ::capExport::exportAllInfo]
}
