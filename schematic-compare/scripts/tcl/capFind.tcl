#===========================================================================
# capFind.tcl — OrCAD Capture 定位函数
#
# 功能：在 Capture GUI 中根据位号或网络名定位并高亮对应的原理图对象。
# 用于对比结果的双击跳转功能。
#
# 用法（在 Capture Tcl 控制台中）：
#   source /path/to/capFind.tcl
#   capFindRefDes "R1"             ;# 定位到器件 R1
#   capFindNet "VCC_3V3"           ;# 定位到网络 VCC_3V3
#   capFindOnPage "PAGE1" "R1"     ;# 在指定页面定位器件
#
# 依赖：OrCAD Capture 17.4+ 的 GUI 环境（需要窗口可见）
#===========================================================================

namespace eval ::schcompare_find {
    variable nullObj NULL
}

# ---------- 基础：获取当前活动设计 ----------

proc ::schcompare_find::get_session {} {
    if {[llength [info commands DboTclHelper_GetSession]]} {
        if {![catch {DboTclHelper_GetSession} sess]} {
            if {$sess ne "" && $sess ne "NULL"} {
                return $sess
            }
        }
    }
    foreach gv {::DboSession_s_pDboSession ::dboSession_s_pDboSession} {
        if {[info exists $gv]} {
            set sess [set $gv]
            if {$sess ne "" && $sess ne "NULL"} {
                return $sess
            }
        }
    }
    error "无法获取 Capture Session"
}

proc ::schcompare_find::get_active_design {} {
    set sess [get_session]
    if {[llength [info commands DboSession]]} {
        catch {DboSession -this $sess}
    }
    if {[catch {set d [$sess GetActiveDesign]} err]} {
        if {[catch {set d [$sess getActiveDesign]} err2]} {
            error "GetActiveDesign 失败: $err / $err2"
        }
    }
    if {$d eq "" || $d eq "NULL"} {
        error "No active design — open a .DSN first"
    }
    return $d
}

# ---------- 获取对象名 ----------

proc ::schcompare_find::obj_name {obj} {
    set lN [DboTclHelper_sMakeCString]
    $obj GetName $lN
    return [DboTclHelper_sGetConstCharPtr $lN]
}

# ---------- 定位到指定器件位号 ----------

proc capFindRefDes {refdes} {
    set lStatus [DboState]
    set design [::schcompare_find::get_active_design]

    set lSchematicIter [$design NewViewsIter $lStatus $::IterDefs_SCHEMATICS]
    set lView [$lSchematicIter NextView $lStatus]
    while {$lView != "NULL"} {
        set lSchematic [DboViewToDboSchematic $lView]
        set lPagesIter [$lSchematic NewPagesIter $lStatus]
        set lPage [$lPagesIter NextPage $lStatus]
        while {$lPage != "NULL"} {
            set lPartInstsIter [$lPage NewPartInstsIter $lStatus]
            set lInst [$lPartInstsIter NextPartInst $lStatus]
            while {$lInst != "NULL"} {
                set lPlacedInst [DboPartInstToDboPlacedInst $lInst]
                if {$lPlacedInst != "NULL"} {
                    set lRefC [DboTclHelper_sMakeCString]
                    $lPlacedInst GetReferenceDesignator $lRefC
                    set rd [DboTclHelper_sGetConstCharPtr $lRefC]
                    if {[string equal -nocase $rd $refdes]} {
                        # 定位到该页面
                        set pgName [::schcompare_find::obj_name $lPage]
                        puts "capFind: found $refdes on page $pgName"
                        # 尝试激活页面并选中对象
                        catch {
                            $lPage Open $lStatus
                            $lPlacedInst Select $lStatus
                        }
                        delete_DboPagePartInstsIter $lPartInstsIter
                        delete_DboSchematicPagesIter $lPagesIter
                        delete_DboLibViewsIter $lSchematicIter
                        $lStatus -delete
                        return $pgName
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
    $lStatus -delete
    puts "capFind: $refdes not found"
    return ""
}

# ---------- 定位到指定网络 ----------

proc capFindNet {netname} {
    set lStatus [DboState]
    set design [::schcompare_find::get_active_design]

    if {[catch {
        set niter [$design NewFlatNetsIter $lStatus]
        set net [$niter NextFlatNet $lStatus]
        while {$net != "NULL"} {
            set nname [::schcompare_find::obj_name $net]
            if {[string equal -nocase $nname $netname]} {
                puts "capFind: found net $netname"
                catch {delete_DboDesignFlatNetsIter $niter}
                $lStatus -delete
                return $nname
            }
            set net [$niter NextFlatNet $lStatus]
        }
        catch {delete_DboDesignFlatNetsIter $niter}
    } err]} {
        puts "capFind: error searching net: $err"
    }
    $lStatus -delete
    puts "capFind: net $netname not found"
    return ""
}

# ---------- 在指定页面上定位器件 ----------

proc capFindOnPage {pageName refdes} {
    puts "capFind: searching for $refdes on page $pageName"
    # 简化版：直接调用 capFindRefDes（完整版应先导航到指定页面）
    return [capFindRefDes $refdes]
}

puts "capFind.tcl loaded — commands: capFindRefDes, capFindNet, capFindOnPage"
