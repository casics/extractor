class OuterClass():
    def outer_function():
        def inner_function1():
            x = 1
        def inner_function2():
            y = 1
        def inner_function3():
            def inner_inner_function():
                z = 1

    class InnerClass():
        def another_function():
            pass

        class InnerInnerClass():
            def innerinner_class_function():
                pass
